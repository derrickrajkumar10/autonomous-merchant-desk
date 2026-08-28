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

Anything else a subsystem needs sits alongside those keys. A payload that is not
JSON-serialisable is refused at write time, because an entry that fails to verify
later is worse than a write that fails now.

The four keys are a convention rather than a constraint, deliberately. Not every
event has reasoning to give — `request_received` does not — and forcing empty keys
onto those entries would buy a schema check at the cost of making the empty ones
look deliberate. The ticket that owns a decision owns proving its entry carries the
reasoning behind it.

### Payload fidelity

The hash is taken over the payload **as Postgres holds it**, not as Python wrote it.
`jsonb` normalises some numbers — the float `1e+16` is stored as
`10000000000000000` — so hashing the Python form would write entries that verify at
the moment of writing and then fail verification for ever after. That is the worst
failure this component has: silent, delayed, and it discredits the one thing the
trail exists to prove. `record()` therefore round-trips the payload through the
database before hashing, which removes the whole class of divergence rather than
enumerating it.

### Corrections

Nothing is edited, so a correction is a new entry naming the entry it corrects:

```json
{
  "corrects_seq": 41,
  "reasoning": "the enquiry was quoting a customer, not instructing the Desk"
}
```

The correcting entry carries the same `subject_id` as the entry it corrects, so a
detail panel showing that subject shows both, in the order they happened.

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

A subsystem writing state of its own passes its connection, so that the state change and
the record of it commit together or not at all:

```python
with pool.connection() as conn:
    conn.execute("INSERT INTO agent_identity ...")
    trail.record(conn=conn, actor="desk", event_type=EventType.AGENT_REGISTERED, ...)
```

Writing the state and then failing to write the entry would leave the trail disagreeing
with reality, which is the one thing it may never do.

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
double-counting. `after_seq` is exclusive, so a caller that has already read up to a
point can ask for what came after it.

### Views

Consumers read a named view rather than the raw table, so the table underneath can
change shape without every consumer changing with it (ADR-0006).

| View | Holds |
|:---|:---|
| `audit_control_room` | Every entry, without the chain hashes. |
| `audit_refusals` | Entries carrying a `reason_code` — what a breakdown of refusals by check reads. |

Neither exposes `prev_hash` or `hash`: those are how the trail proves itself, not
something a consumer draws.

ADR-0006 also names per-agent detail panels as a consumer. They read
`audit_control_room` filtered by `subject_id`, and a view that hard-codes nothing but
a `WHERE` clause the caller must supply anyway would earn its keep from nobody — so
there isn't one.

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
