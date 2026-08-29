# Ticket 01 — The audit trail

**What shipped:** a permanent, searchable record of every decision the Desk makes, built
so that nobody — including us — can quietly change it afterwards.

This document is layered. Section 1 assumes nothing at all; each section adds a little
more. Stop wherever you have what you need — the code is at the end, not the start.

| | |
|:---|:---|
| **Issue** | [#18](https://github.com/derrickrajkumar10/autonomous-merchant-desk/issues/18), under spec [#2](https://github.com/derrickrajkumar10/autonomous-merchant-desk/issues/2) |
| **Builds on** | Nothing. This is the first code in the repository. |
| **Everything else builds on it** | Every later ticket either writes here or reads here. |

---

## 1. The situation, with no jargon

We are building a shop that sells to AI programs with no human involved in the sale. It
will refuse some of them. It will haggle with others, and sometimes walk away from a deal
rather than take it.

Afterwards, somebody is going to ask questions:

- *"Why did you turn that buyer away?"*
- *"Why did you refuse the discount but offer a bundle?"*
- *"You paid the more expensive supplier — explain."*

The shop has to be able to answer. Not "it seemed right at the time" — actually answer,
with what it knew and what it decided.

### Why not just a log file?

That's the obvious idea, and it fails for two separate reasons.

**A log file doesn't answer questions.** You can't ask a text file *"how many buyers did
we turn away last week, and for which reason?"* You can grep it and squint. That isn't an
answer, that's a chore that produces a guess.

**A log file we can edit proves nothing.** This is the deeper problem. If the shop keeps
its own record, and the shop can change that record, then the record is worth exactly as
much as the shop's word — which is what it was supposed to replace. Anyone reviewing us
can point out that we could have tidied it up before showing them.

That second problem is the one this ticket takes seriously, because the whole project's
posture is *evidence over assertion*. We go as far as refusing to take our own bank's
word for things later on. A record we could doctor would make all of that hollow the
moment somebody asked.

---

## 2. What we built, in plain words

**A table in a database, not a file.** So questions like "all refusals in this hour" are
things you *ask*, not things you go and count.

**Nothing can ever be changed or removed.** Not by us, not by application code, not by
somebody with a database password typing an `UPDATE`. If a decision turns out to be
wrong, you don't fix the old record — you add a new one saying so. The old one stays.

**Each entry is sealed to the one before it.** Every entry carries a fingerprint of
itself *and* of the entry before it. Change any old entry and its fingerprint no longer
matches, and every entry after it is now sealed to something that no longer exists. One
pass through the record finds it. This is the part that makes "we couldn't have doctored
this" a demonstration rather than a promise.

**Refusal reasons come from a fixed list.** Not free-form sentences. So refusals *add up*
into a number instead of scattering into a thousand near-identical phrasings.

---

## 3. Building up the ideas

### 3.1 What one entry holds

Every decision, from every part of the system, is written in the same shape:

| Column | Holds | Example |
|:---|:---|:---|
| `seq` | Position in line: 1, 2, 3… never a gap | `41` |
| `ts` | When it happened, from the database's own clock | `2026-08-29T12:00:03Z` |
| `actor` | Who acted | `desk` |
| `event_type` | What happened — from a fixed list | `check_1_identity_refused` |
| `subject_id` | What it happened *to* | `agent-kBTf…` |
| `reason_code` | Why refused — from a fixed list, empty if not a refusal | `agent_signature_invalid` |
| `payload` | The reasoning, the evidence, the resulting change | see below |
| `prev_hash` | The previous entry's fingerprint | `a216053ba3125ee7…` |
| `hash` | This entry's own fingerprint | `2c9a271887d1d0bc…` |

One shape for everything, deliberately. A new consumer — a dashboard, a metrics script,
somebody's analysis — learns one format, not one per subsystem.

The `payload` is the free-form part, and it carries the three things that turn *what
happened* into *why*:

```json
{
  "check": 3,
  "reasoning": "requested 2400 against 1800 remaining on the open mandate",
  "evidence": { "requested_minor": 240000, "remaining_minor": 180000 },
  "state_change": { "deal": "refused" }
}
```

Reasoning, evidence, and what actually changed as a result. A refusal that names the
check that fired proves that check exists. A generic "request rejected" proves nothing —
you'd have to take our word that anything was checked at all.

### 3.2 Fingerprints (hashes)

A **hash** is a function that turns any amount of data into a short fixed-length string.
Two useful properties:

- Same input, always the same output.
- Change the input by one character, and the output is completely different — not
  slightly different, entirely different.

It only goes one way: you can't work backwards from the fingerprint to the data. We use
SHA-256, which produces 64 hex characters.

So a hash is a compact way to say *"here is proof of exactly what this said"*, without
carrying the whole thing around.

### 3.3 Chaining: why one changed entry breaks everything after it

Here's the trick. Each entry's fingerprint is computed over its own contents **plus the
previous entry's fingerprint**.

```
entry 1 ─hash─▶ a216…
                  │  (entry 2 includes a216… in what it hashes)
entry 2 ─hash─▶ 2c9a…
                  │
entry 3 ─hash─▶ 8f1d…
```

Now suppose someone goes back and edits entry 1 — changes who acted, say. Entry 1's
contents no longer produce `a216…`, so it no longer matches its own recorded fingerprint.
And entry 2 still says "I follow `a216…`", which is now a description of an entry that
doesn't exist any more.

To cover it up you'd have to recompute entry 1's fingerprint, then entry 2's (because it
contains entry 1's), then entry 3's, then every entry ever written. And anyone who wrote
down the last fingerprint at any earlier moment would still catch you.

Checking is one walk from the start: does each entry hash to what it says, and does each
one point at the one before it? That is `trail.verify()`, and it's cheap enough that
tests run it constantly.

**The one thing a chain can't see** is history cut off at the *end*. Delete the last ten
entries and what remains is perfectly consistent — it just stops earlier. So `verify()`
optionally takes a fingerprint you recorded earlier and checks the record still ends
where you last saw it.

### 3.4 Append-only, enforced by the database

"Nothing updates or deletes" could have been a rule in a document that everybody
promises to follow. It isn't. It's enforced by the database itself: `UPDATE`, `DELETE`
and `TRUNCATE` on this table all raise an error, from triggers installed with the table.

The difference matters. A convention is enforced by whoever is reviewing the code that
day. A trigger is enforced at 3am by a database that doesn't care who is asking.

There's a natural question here: *if the database already blocks changes, why bother
with the chain?* Because they defend against different people. The triggers stop the
Desk's own code from editing history. The chain answers "could an operator with full
database access have doctored this?" — and an operator can switch triggers off. The
tests for the chain do exactly that, on purpose: they disable the triggers first,
because that is the only adversary the chain exists to catch.

### 3.5 Closed vocabularies

Two of the columns can only hold values from a fixed list:

- **`event_type`** — what happened: `agent_registered`, `check_1_identity_passed`,
  `deal_closed`, `walked_away`, `match_found`… about thirty of them.
- **`reason_code`** — why something was refused: `agent_signature_invalid`,
  `mandate_expired`, `exceeds_remaining_balance`, `below_margin_floor`…

Why closed? Because a refusal reason drawn from a fixed set **aggregates into a number**.
"Refusals at check 3 this week: 47." If reasons were free text you'd have
`"insufficient funds"`, `"not enough balance"` and `"exceeds balance"` all meaning the
same thing and none of them counting together.

And the list is closed in *two* places — a Python enum and a matching Postgres type — so
even code that goes around our own API and inserts directly cannot smuggle in a new
string. Adding a member means changing both, which is exactly the point: a new refusal
reason should be a visible decision in review, not something that quietly appears in
production one day.

### 3.6 The sequence, and why it needs a lock

Entries are numbered 1, 2, 3 with no gaps, because timestamps are not a reliable order —
two entries written in the same millisecond can tie, and a tie is ambiguity.

But several parts of the Desk write at once. If two writers both read "the last entry is
41" and both write 42, you get a mess. So appends take a lock for the instant it takes to
claim the next number and link onto the previous entry. The timestamp is taken *inside*
that lock too, so a later entry can never carry an earlier time — which is what makes the
sequence a genuine tie-break rather than a second opinion.

Sixteen threads writing 25 entries each is a test in the suite, checking exactly that.

### 3.7 The subtlest bug in the whole component

This one is worth reading slowly, because it's the kind of thing that looks fine, passes
every test you thought to write, and destroys the component's credibility six weeks
later.

The database normalises some numbers when it stores JSON. Hand Postgres the float
`1e+16` and it stores `10000000000000000`. Same number, different text.

The chain is computed over an entry's contents — including the payload. So if we hash
the payload **as Python wrote it**, but verification later reads the payload back **as
Postgres stored it**, the two produce different fingerprints for an entry nobody touched.

The result: an entry that writes cleanly, verifies at the moment of writing, and then
fails verification for ever afterwards. The trail accusing itself of tampering when
nothing had tampered. Silent, delayed, and it discredits the exact thing the trail exists
to prove.

The fix is to round-trip the payload through the database *before* hashing it, so we hash
what will actually be stored. That removes the whole category of problem rather than
patching the one number we happened to notice. It has its own test file with a list of
awkward values.

### 3.8 Views: consumers don't read the raw table

Three consumers read this trail: the control room (the front-end), the published metrics,
and the test suite. None of them read the table directly. They read named **views** —
saved queries that look like tables:

| View | Holds |
|:---|:---|
| `audit_control_room` | Every entry, without the chain fingerprints |
| `audit_refusals` | Only entries carrying a reason code |

Two reasons. The table underneath can change shape without every consumer changing with
it. And neither view exposes `prev_hash` or `hash`, because those are how the trail
proves itself, not something a dashboard should be drawing.

---

## 4. The code

| File | What it is |
|:---|:---|
| [desk/audit/vocabulary.py](../../desk/audit/vocabulary.py) | The two closed lists, and rejecting anything outside them |
| [desk/audit/entry.py](../../desk/audit/entry.py) | One entry, and how its fingerprint is computed |
| [desk/audit/schema.py](../../desk/audit/schema.py) | The table, the triggers, the views, the database types |
| [desk/audit/trail.py](../../desk/audit/trail.py) | Writing, querying, verifying |

### Writing

```python
trail.record(
    actor="desk",
    event_type=EventType.CHECK_2_MANDATE_VALIDITY_REFUSED,
    subject_id="agent-7",
    reason_code=ReasonCode.MANDATE_EXPIRED,
    payload={
        "check": 2,
        "reasoning": "the open mandate expired before the request arrived",
        "evidence": {"expires_at": "...", "received_at": "..."},
        "state_change": {"deal": "refused"},
    },
)
```

Writing is synchronous with the decision it records — the decision isn't "made" until
it's written. A decision that happened but wasn't recorded is worse than no decision,
because from then on every consumer disagrees with reality.

### Reading

```python
trail.query(reason_code=ReasonCode.PROMPT_INJECTION_DETECTED)  # for the metrics
trail.query(subject_id="agent-7")                              # for a detail panel
trail.query(since=window_start, until=window_end)              # for a batch report
trail.query(after_seq=last_drawn)                              # for the control room
```

`since` is inclusive and `until` is exclusive, so two adjacent windows tile perfectly
without double-counting anything on the boundary. `after_seq` is how the front-end tails
the record without re-drawing what it already drew.

### Verifying

```python
report = trail.verify()
report.ok          # False if the chain does not hold
report.break_at    # the entry number where it broke
report.break_kind  # entry_missing | link_broken | content_altered | head_unexpected
```

Note that it reports *where* and *how*, not just yes or no. "Something's wrong" is not
evidence; "entry 41 does not hash to its recorded fingerprint" is.

Hashing lives in Python rather than in the database on purpose: anyone holding a dump of
the table can recheck the whole chain without needing our Postgres, or us.

---

## 5. Decisions worth knowing, and what each cost

| Decision | Why | What it costs |
|:---|:---|:---|
| A table, not a log file | questions get answered, not grepped | Postgres is now a hard dependency |
| Hash-chained | "could you have doctored this?" gets a demonstration | every write does a little more work |
| Append-only in triggers | enforced at 3am, not by a reviewer | corrections are new entries; there is no undo |
| Closed vocabularies | refusals aggregate into metrics | adding a reason means a code change *and* a database migration |
| One lock per append | a gapless order, and timestamps that can't contradict it | appends serialise; fine at our volume |
| Hash the payload as stored | kills the silent-verification-failure bug | one extra database round-trip per write |
| Views per consumer | the table can change shape underneath | one more thing to keep in step |

---

## 6. What this ticket deliberately does *not* do

| Not this | Whose job |
|:---|:---|
| Any actual decision logic | Every later ticket. This one builds the surface they write to |
| Sending entries to the front-end live | Ticket 27, the control room |
| Turning entries into published numbers | Ticket 20, metrics |
| Signing entries with a key | Not needed — the chain gives tamper *evidence*, which is the property required here |
| Retention, archival, pruning | Out of scope for this build |

That fourth row is worth a second's thought, since ticket 02 signs things. Signing and
chaining answer different questions. A chain proves *nothing was altered after the fact*.
A signature proves *who produced this*. The trail only needs the first.

---

## 7. Seeing it for yourself

```bash
uv sync --extra dev
.venv/Scripts/python.exe -m pytest tests/audit -q     # 61 tests, spins up its own Postgres
```

The test files are the best tour of the component, and each one is named for the property
it defends: `test_chain.py` (tampering, with the triggers switched off),
`test_append_only.py` (the database refusing to change history),
`test_concurrency.py` (sixteen writers at once), `test_payload_fidelity.py` (section 3.7's
awkward numbers), `test_query.py`, `test_views.py`, `test_vocabulary.py`.

This snippet needs no database — it builds two entries by hand and then tries to doctor
one. Paste it into `python`:

```python
import dataclasses
from datetime import UTC, datetime
from desk.audit import GENESIS_HASH, AuditEntry, EventType, ReasonCode

def link(seq, prev_hash, reasoning):
    draft = AuditEntry(
        seq=seq,
        ts=datetime(2026, 8, 29, 12, 0, seq, tzinfo=UTC),
        actor="desk",
        event_type=EventType.CHECK_1_IDENTITY_REFUSED,
        subject_id="agent-7",
        reason_code=ReasonCode.AGENT_SIGNATURE_INVALID,
        payload={"reasoning": reasoning},
        prev_hash=prev_hash,
        hash="",
    )
    return dataclasses.replace(draft, hash=draft.recompute_hash())

first = link(1, GENESIS_HASH, "no agent is registered under that key")
second = link(2, first.hash, "the signature does not verify")

print("first :", first.hash[:16])
print("second:", second.hash[:16], "chains onto", second.prev_hash[:16])

# Now doctor the first entry: same recorded fingerprint, different contents.
doctored = dataclasses.replace(first, actor="somebody else")
print("recorded  :", doctored.hash[:16])
print("recomputed:", doctored.recompute_hash()[:16])
print("altered?", doctored.recompute_hash() != doctored.hash)
```

`second` chains onto `first`'s fingerprint, and the doctored entry no longer hashes to
what it claims. That is the whole mechanism, in twenty lines.

---

## 8. Glossary

| Term | Means |
|:---|:---|
| **The Desk** | Our system — the merchant. What we are building. |
| **Audit trail** | The append-only, hash-chained record of every decision. This ticket. |
| **Entry** | One decision, written down. |
| **Hash** | A short fixed-length fingerprint of some data. Same data, same fingerprint. |
| **SHA-256** | The specific hash we use. 64 hex characters. |
| **Hash chain** | Each entry's fingerprint covers the previous entry's, so altering history is visible. |
| **Append-only** | Rows can be added, never changed or removed. Enforced by the database. |
| **Genesis hash** | Sixty-four zeroes — what the very first entry chains onto. |
| **Reason code** | A refusal reason from a closed list, so refusals aggregate. |
| **Event type** | What happened, from a closed list. |
| **Payload** | The free-shaped JSON carrying reasoning, evidence and state change. |
| **View** | A saved query that behaves like a table; what consumers read instead of the raw table. |
| **Trigger** | Database code that runs automatically on an operation — here, to forbid it. |
| **Advisory lock** | A lock code takes voluntarily to serialise a section — here, claiming the next sequence number. |

---

## 9. Next

**Ticket 02 — agent registration and identity.** The first thing that actually writes
here. Every registration, and every request the Desk identifies or refuses, becomes an
entry in this table — which is also how ticket 02's tests check their work: they assert
on what got written, not on what the code returned.

That pattern holds for the rest of the build. This ticket is the assertion surface for
everything after it, which is why it was built first and built completely.

→ [Ticket 02 — Agent registration and identity](ticket-02-agent-identity.md)
