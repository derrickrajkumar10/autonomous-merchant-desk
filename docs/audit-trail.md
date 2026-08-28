# The audit trail

Every decision the Desk makes is written here, and three consumers read from it and
from no other source: the control room, the published metrics, and the test suite.
One contract, exercised three ways.

This document is the contract. It is written down before anything consumes it so the
control room can be built against a stable shape. Decisions behind it:
[ADR-0006](adr/0006-audit-trail-is-a-hash-chained-postgres-table.md).

---

## The entry

One shape for every subsystem, so a new consumer has one format to learn.

| Column | Type | Meaning |
|:---|:---|:---|
| `seq` | `bigint` | Monotonic, gapless, starting at 1. The unambiguous order, when timestamps collide. |
| `ts` | `timestamptz` | When the decision was made, taken from the database clock. |
| `actor` | `text` | Who acted — `desk`, an agent id, `wallet`. Never blank. |
| `event_type` | `audit_event_type` | What happened. A **closed** enum. |
| `subject_id` | `text` | What it happened to — an agent, a deal, a bank line. Never blank. |
| `reason_code` | `audit_reason_code` | Why it was refused, or what a settlement proof concluded. A **closed** enum, `NULL` when the event is not a refusal. |
| `payload` | `jsonb` | The rest of FR-10.1: the reasoning, the evidence, the resulting state change. |
| `prev_hash` | `text` | The previous entry's `hash`. Sixty-four zeroes for the first entry. |
| `hash` | `text` | SHA-256 over this entry's own contents plus `prev_hash`. |

### The payload

`payload` is one free-shaped JSON object rather than a column each, because FR-10.1's
remaining three parts differ in shape per subsystem while the entry does not. The
convention every write site follows:

```json
{
  "check": 3,
  "reasoning": "requested 2400 against 1800 remaining on the open mandate",
  "evidence": { "requested_minor": 240000, "remaining_minor": 180000 },
  "state_change": { "deal": "refused" }
}
```

Anything else a subsystem needs sits alongside those keys. A payload that will not
survive a round trip through `jsonb` unchanged is refused at write time, because an
entry that fails to verify later is worse than a write that fails now.

---

## The vocabularies

Both are closed sets, shared verbatim by the Desk, the control room and the metrics,
and both exist as Postgres enum types as well as Python enums — so a write that goes
around the trail still cannot smuggle in a novel string. Growing either means adding
a member **and** migrating the database type; installing against a database whose type
disagrees raises `SchemaDrift` rather than running on quietly.

### `reason_code` — the seventeen ADR-0006 members

| Check / policy | Codes |
|:---|:---|
| 1 — identity | `agent_signature_invalid` |
| 2 — mandate validity | `mandate_signature_invalid`, `mandate_expired`, `agent_mandate_mismatch` |
| 3 — spend authority | `exceeds_remaining_balance`, `category_not_authorised`, `outside_validity_window` |
| 4 — replay and freshness | `nonce_replayed`, `request_stale` |
| 5 — inspection | `prompt_injection_detected`, `escalation_pattern_detected` |
| Negotiation and the ladder | `below_margin_floor`, `agent_blocked`, `ceiling_exceeded_for_tier` |
| Treasury | `treasury_buffer_insufficient` |
| Settlement proof | `bank_line_unmatched`, `bank_line_ambiguous` |

### `event_type`

Each of the five checks passes or refuses under its own member, so that refusals
break down by check (§9) without a consumer reading into a payload.

`agent_registered`, `request_received`,
`check_1_identity_passed` / `_refused`,
`check_2_mandate_validity_passed` / `_refused`,
`check_3_spend_authority_passed` / `_refused`,
`check_4_replay_freshness_passed` / `_refused`,
`check_5_inspection_passed` / `_refused`,
`negotiation_message_sent`, `lever_offered`, `deal_closed`, `walked_away`,
`receipt_issued`, `procurement_triggered`, `quote_received`, `supplier_selected`,
`order_placed`, `treasury_gate_evaluated`, `bank_line_received`, `match_found`,
`exception_recorded`, `trust_score_changed`, `rung_changed`.

---

## Writing

Writing is synchronous with the decision it records. A decision that happened but was
not recorded is worse than no decision, because every downstream consumer then
disagrees with reality.

```python
from psycopg_pool import ConnectionPool
from desk.audit import AuditTrail, EventType, ReasonCode, install_schema

with ConnectionPool(dsn) as pool:
    with pool.connection() as conn:
        install_schema(conn)          # idempotent

    trail = AuditTrail(pool)
    entry = trail.record(
        actor="desk",
        event_type=EventType.CHECK_2_MANDATE_VALIDITY_REFUSED,
        subject_id="agent-7",
        reason_code=ReasonCode.MANDATE_EXPIRED,
        payload={"check": 2, "reasoning": "...", "evidence": {}, "state_change": {}},
    )
```

Appends serialise on a single advisory lock, so the sequence stays gapless and each
entry chains onto the entry that really precedes it, however many writers are running.

**Nothing updates or deletes.** That is enforced by the database, not by convention:
`UPDATE`, `DELETE` and `TRUNCATE` on the table all raise. A correction is a new entry
naming the earlier subject.

---

## Reading

One method, composable filters, ordered by `seq`.

```python
trail.query(reason_code=ReasonCode.PROMPT_INJECTION_DETECTED)   # for the metrics
trail.query(subject_id="agent-7")                               # for a detail panel
trail.query(since=window_start, until=window_end)               # for a batch report
trail.query(after_seq=last_drawn)                               # for the control room
```

`since` is inclusive and `until` exclusive, so adjacent windows tile without
double-counting. `after_seq` is exclusive, which is how the control room tails the
trail without re-reading what it has already drawn.

---

## The chain

Each entry hashes its own contents together with the previous entry's hash, over a
canonical JSON form (keys sorted, no incidental whitespace, timestamps normalised to
UTC). Hashing lives in Python rather than in the database, so anyone holding the
entries — including a judge with a dump of the table — can recompute it without
Postgres.

```python
report = trail.verify()
report.ok               # False if the chain does not hold
report.break_at         # the seq where it broke
report.break_kind       # entry_missing | link_broken | content_altered | head_unexpected
report.detail           # what to say about it
```

Verification is a single streaming forward pass, cheap enough to run in tests and
after a batch run.

Linkage is also enforced on insert, so a broken link cannot be appended in the first
place. Combined with append-only, that means the chain only breaks if someone goes
around the application with database privileges — which is exactly the adversary the
chain exists to catch, and exactly what the tests simulate.

### One honest limit

A hash chain cannot see history lopped off its own **head**: what remains is
internally consistent. `verify(expected_head_hash=...)` closes that when a caller
already knows where the trail ended. Making it unconditional needs an anchor outside
the database — signing entries, or publishing the head somewhere the Desk does not
control — which is a different property and deliberately out of scope for now
(Spec 01, Out of Scope).

---

## Running the tests

The properties under test — a monotonic sequence under concurrent writes,
structurally enforced append-only, an enum the database itself refuses to widen — are
properties of Postgres, so the suite runs against a real one. It finds it by:

1. `STITCHAI_TEST_DATABASE_URL`, if set.
2. An embedded server from the `pgserver` dev dependency, otherwise.

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/python -m pytest        # .venv/Scripts/python.exe on Windows
```
