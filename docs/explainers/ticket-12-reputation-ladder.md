# Ticket 12 — What an agent's record buys it, and why patience is the only way up

*Ticket 12 of the StitchAI build. The two tickets before it watched a single message
and a single agent's history for bad behaviour. This one decides what the Desk does
with a well-behaved agent — and makes sure "reward good behaviour" does not turn into
the attack it was meant to stop.*

Read the sections in order and stop wherever you have what you need. The first three
have no jargon in them; the code is at the end.

---

## 1. The situation

The Desk treats every agent identically, and that is wrong in two directions at once.

An agent that registered a minute ago and has never completed a deal is allowed to
spend exactly as much as one that has closed fifty clean deals over three months. That
is too generous to the stranger: the Desk is extending real spending authority to
someone it knows nothing about. And it is a waste of effort on the regular: the Desk
runs its most expensive, most careful checks just as hard on a party it has every
reason to trust as on one it has every reason to doubt.

The obvious fix is to let a good record earn a larger allowance and a lighter touch.
That is also the problem.

If good behaviour visibly raises the ceiling, an agent that understands the rule has a
strategy. Do a run of small, clean, unremarkable deals — cheap, and every one of them
genuinely fine — until the allowance is at its highest. Then, once, ask for something
far bigger than anything before it, at the moment the Desk is least suspicious. The
small deals were never the point; they were the price of admission for the one that
was.

This has a name — **trust farming** — and it is not a hypothetical the Desk might one
day face. It is the rational way to play a naive reputation system, and the project's
red team will play it. A reputation feature that can be farmed is not a safety feature;
it is a new way in.

This ticket builds a reputation system that cannot be farmed, and says plainly what
that costs.

---

## 2. A ladder, not a dial

The tempting design is a formula: `ceiling = f(score)`, some smooth curve that rises as
the agent's score rises. It is tempting because it feels precise.

The Desk uses a **ladder** instead — a short list of fixed steps, each with a concrete
spending limit written on it. Rung 0: 2,000 rupees. Rung 1: 15,000. Rung 2: 75,000.
Rung 3: 300,000. An agent is always on exactly one rung, and the rung is what the Desk
acts on.

Two reasons, and the first is almost aesthetic until you think about it. A person
reading the audit trail can see *moved from newcomer to regular* at a glance and know
what changed. *Ceiling recomputed to 47,318.55* tells them nothing they can hold in
their head. The trail is the product here — it is what a panel of judges reads, what
the control room draws — and "legible to a person" is a requirement, not a nicety.

The second reason is the one that stops farming, and it needs its own section.

---

## 3. The thing volume cannot buy

Each rung carries a **dwell time**: the least amount of *elapsed time* an agent must
spend on a rung before it is allowed to climb to the next one. Rung 0's is one day.
Rung 1's is three. Rung 2's is a week.

This is the whole anti-farming mechanism, and it works because time is the one cost a
farmer cannot pay with volume. An agent can do a hundred clean deals in an hour. Its
score will happily climb past the threshold for the next rung. It still does not move,
because it has not been on its current rung long enough — and there is nothing it can
*do* to make that faster. A thousand more deals do not help. The clock is the gate.

So the farming attack changes shape. To get a large ceiling, the agent now has to
genuinely wait — days on rung 0, then days on rung 1, then a week on rung 2 — behaving
well the entire time, with a real identity the whole run traces back to. That is no
longer "farming". That is just being a customer for a month. If an attacker is willing
to do that, patiently, in the open, the Desk has extracted a month of good behaviour
and a fully attributable identity as the price of one large transaction — and the
behavioural score from the previous ticket is still watching for the moment the
character changes.

The dwell time is the part of this design most likely to be dropped as fiddly. Without
it, the ladder is just a slower version of the dial, and the farming attack works
again.

---

## 4. Slow up, fast down, and quietly back to normal

The score itself is a number between 0 and 1. A new agent starts at 0.1.

It moves **asymmetrically**, on purpose. A clean completed deal adds a small fixed
amount — 0.04. A signal from check 5 — an injection attempt caught by the Inspector, or
an escalation pattern caught by the behavioural score — subtracts *five times* that.
Trust is slow to earn and fast to lose, and the multiple is enforced in the code rather
than left to whoever tunes the numbers: a check-5 signal that cost the same as a clean
deal earned would make farming a break-even game again.

Enough check-5 signals — three, by default — and the agent is **blocked**. A blocked
agent is refused outright, before any negotiation opens, and stays blocked. Unblocking
is deliberately not built: a known-hostile party is not something the Desk needs a
workflow for.

And a score that has climbed above baseline **decays** back toward it while the agent
is inactive. A little each day. This is not a punishment — it is what makes a dormant
high-trust identity worthless to steal. If an attacker compromises the credentials of
an agent that earned its way to rung 3 and then went quiet, they inherit an agent
that is drifting back to ordinary by the day. Decay only ever moves a score *down*: an
agent sitting at baseline, or a blocked one, is left exactly where it is. Time alone
never earns trust.

Every one of these movements — each score change, each rung change, the block — is
written to the audit trail with its cause, in the same database transaction as the
change itself. An agent's standing at any past moment can be reconstructed from the
trail alone.

---

## 5. Where it sits, and the one rule it shares with check 5

Reputation runs *after* the four deterministic checks have passed, as a separate step
called the **standing gate**. The gate does one thing: it compares the amount being
asked for against the ceiling of the agent's current rung, and refuses —
`ceiling_exceeded_for_tier` — if it is over. (It also refuses a blocked agent, under
`agent_blocked`.)

This is where the trust-farming grab lands. The agent's mandate permits the large
amount — the human set a generous budget. Check 3 passed it against that mandate. The
behavioural score may or may not have caught the shape. But the agent's rung ceiling
has not moved, because rungs move on elapsed time and this agent has not spent the
time. The gate refuses it.

The rule reputation shares with check 5 is the important one:

> **Reputation decides how much an agent may do. It never decides whether the checks
> run.**

No rung, however high, skips a deterministic check or shortens one. A trusted agent
gets a larger ceiling and a lighter check-5 touch — it never gets a pass on check 1, 2,
3 or 4. This is the same inversion the trust-spine ticket warns about
([ticket 06](ticket-06-spine-ordering.md)), seen from the other side: there, the worry
is a check being skipped for a *bad* reason; here, it is a check being skipped for a
*good* one. Both are the same bug.

That is also why the reputation package is not part of the spine and a spine module may
not import it — a test enforces this. If check 3 read an agent's rung, check 3's answer
would become a function of the agent's history, and it would stop being the flat,
certain thing the whole design rests on.

This closes a loop the earlier tickets left open. The five checks were described as a
pipeline — request goes in one end, decision comes out the other. With reputation they
are a **cycle**: check 5 watches behaviour, behaviour feeds the score, the score sets
the rung, the rung gates authority, and the next request meets a Desk that has changed
its mind about this agent.

---

## 6. Watching it happen

One agent, one lifetime, the default numbers. This is the output of
`tests/reputation/test_explainer_walkthrough.py`, asserted rather than described, so it
cannot drift without the suite noticing.

```
One agent on the ladder (default policy):
  registers                       score 0.10  rung 0 newcomer     ceiling 2000.00 INR
  6 clean deals, one day          score 0.34  rung 0 newcomer     held by the 1-day dwell
  1 clean deal, two days on       score 0.36  rung 1 regular      ceiling 15000.00 INR
  offers 50,000 for one deal      refused: ceiling_exceeded_for_tier
  3 check-5 signals               blocked
  offers 100 the next day         refused: agent_blocked
```

- **6 clean deals, one day** — the score runs straight past rung 1's threshold of 0.30.
  The agent does not move, because it has been on rung 0 for less than a day. This is
  the farming attempt failing.
- **1 clean deal, two days on** — now the dwell is served, so this deal earns the climb.
  One rung, not two, however far the score has run ahead.
- **offers 50,000** — a perfectly valid request: real identity, real mandate with a
  budget that covers it, inside every deterministic check. Refused by the rung ceiling
  of 15,000, which two clean days does not raise.
- **3 check-5 signals → blocked** — and from then on even a 100-rupee request, valid in
  every other respect, is refused at the gate.

---

## 7. What this costs, honestly

**A patient attacker is not stopped — they are converted into a customer.** Everything
in section 3 is true, but the flip side is: if someone will genuinely wait a month,
behaving well, with an attributable identity, they can reach a high rung. This design
does not claim to stop that. It claims to make it expensive, slow, visible, and
attributable — and to keep the behavioural score watching for the moment the patient
good behaviour turns into the thing it was cover for.

**The numbers are guesses.** The rung ceilings, the 0.04 increment, the ×5 penalty, the
three-signal block, the decay rate — all of it is tuning. A reviewer should be arguing
about whether 15,000 is the right second-rung ceiling, not reverse-engineering where it
came from. The one thing that is *not* tuning, and is asserted in the suite, is that a
signal costs strictly more than a deal earns.

**Decay is lumpy.** Rather than write a trail entry for every sub-rupee drop between two
deals an hour apart, decay accumulates and is recorded in one entry once it crosses a
small threshold — roughly every twelve hours of real inactivity. An active agent never
triggers it. The trail stays readable; the trade is that a decay entry's timestamp is
approximate to within half a day.

**The gate is built but not yet wired into a single request pipeline.** This ticket
delivers the ladder, the gate, and the seam. The end-to-end flow — spine, then gate,
then check 5, then negotiation, then settlement, then "record the clean deal" — is
assembled by the batch runner and the control-room fork. Until then the pieces are
driven directly, which is exactly how the tests exercise them.

---

## 8. What this ticket deliberately does not do

- **It does not compute check-5 signals.** Those are produced in
  [`desk.inspector`](ticket-10-the-inspector.md) and
  [consumed here](ticket-11-behavioural-score.md). Sudden escalation relative to an
  agent's own history is a check-5 signal, not a reputation rule — the two subsystems
  compose, and neither reimplements the other.
- **It does not price by reputation.** The negotiation engine bargains the same way
  with a stranger as with a regular ([ticket 08](ticket-08-negotiation.md)). Reputation
  gates the ceiling and the scrutiny tier, never the price — a fixed baseline that
  quietly priced by reputation would make ticket 21's learned-vs-fixed comparison
  meaningless.
- **It does not do cross-agent reputation, shared blocklists, or reputation for
  principals.** One score per agent identity, and nothing shared between them.
- **It does not unblock.** A blocked agent stays blocked; the database refuses the
  transition back.
- **It does not let a rung skip a check.** Ever. See section 5.
- **It is not a learned model.** It is bookkeeping around two numbers and a clock.

---

## 9. The vocabulary, now that you need it

- **Trust score** — the per-agent number, in `[0, 1]`, starting at `0.1`, that gates the
  spend ceiling and the scrutiny tier. Rises 0.04 per clean deal, falls five times that
  per check-5 signal.
- **Rung** — one discrete step on the ladder. Carries a spend ceiling, a scrutiny tier,
  the score that makes it available, and a dwell time. An agent is on exactly one.
- **Spend ceiling** — the most one deal may be worth for an agent, set by its rung. This
  is the Desk's own limit and is separate from — and smaller than — any ceiling a
  principal's mandate sets.
- **Dwell time** — the least elapsed time an agent must spend on a rung before climbing
  off it. The anti-farming mechanism: volume cannot pay it.
- **Scrutiny tier** — one of three levels (`close`, `standard`, `light`) controlling how
  hard check 5 looks at an agent. Computed here, consumed in `desk.inspector`.
- **Standing** — an agent's score, rung, ceiling, scrutiny tier and blocked flag,
  together, as the Desk would act on them right now.
- **Standing gate** — the step after the spine that refuses a request over the agent's
  rung ceiling (`ceiling_exceeded_for_tier`), or a blocked agent (`agent_blocked`).
- **Trust farming** — building a clean record with small deals, then attempting one
  disproportionate deal. What the dwell time exists to defeat.
- **Blocked** — terminal. Enough check-5 signals have accrued that the Desk will not
  transact with this agent, and there is no path back.
- **Cycle, not pipeline** — behaviour feeds reputation, reputation gates authority; the
  five checks are not a straight line.

---

## 10. Where the code lives

```
desk/reputation/policy.py    every tuned number, in one replaceable object
desk/reputation/ladder.py    the rungs, and the decay and rung arithmetic as pure functions
desk/reputation/schema.py    one row per agent; the score bound and the no-unblock rule are the database's
desk/reputation/store.py     ReputationLadder: standing, record_clean_deal, record_check5_signal
desk/reputation/gate.py      StandingGate: the one refusal, run after the spine, skipping nothing
desk/audit/vocabulary.py     three new event types: standing_gate_passed / _refused, agent_blocked
```

`store.py` is the heart of it: everything is bookkeeping around a score and a rung
index, with each movement written to the trail in the same transaction as the state
change. `ladder.py` holds the numbers and the two pure functions — `highest_available`
(which rung a score reaches) and `decayed` (a score after some idle time) — so the
arithmetic can be read and tested without a database.

The three new event types are a deliberate addition to a closed vocabulary
([ADR-0006](../adr/0006-audit-trail-is-a-hash-chained-postgres-table.md)). The score
change and the rung change already had members (`trust_score_changed`, `rung_changed`);
what is new is the gate's pass/refuse pair and the moment of blocking. They are
separate members rather than one with a flag because the control room subscribes by
event type, and "this agent was blocked" is a different thing on screen from "this
request was over its ceiling".

---

## 11. If you want to read the code

Start with `desk/reputation/ladder.py` — the module docstring lists what a rung
carries and why, and the `LADDER` tuple is the whole ladder in six lines. Then
`desk/reputation/store.py`, whose docstring lists the four things that move a score.

The tests are the other way in. `tests/reputation/test_score_and_rung.py` drives
`ReputationLadder` directly with a controlled clock — dwell time and decay are about
elapsed time, so every method takes an optional `now` and a test advances a `datetime`
instead of sleeping. `tests/reputation/test_standing_gate.py` builds real signed
requests, sends them through `TrustSpine.receive`, and then hands the passed outcome to
the gate — so the `SpineOutcome` the gate reads is one a running Desk would have
produced.
`test_standing_gate.py::test_no_rung_however_high_causes_a_deterministic_check_to_be_skipped`
is the guard on section 5, and `tests/spine/test_no_model_call.py` is what keeps a
spine module from importing this package.

**Counts, actually run:** 19 tests in `tests/reputation/` — 12 on the score and rung
arithmetic (including one that pins a custom ladder's rung drops to the ladder that
was injected, not the default one), 6 through the standing gate, 1 the walkthrough.
523 in the suite as a whole, plus the same three skipped as before — the AP2
conformance test, ticket 09's Razorpay test, and ticket 10's real-Inspector corpus
test.

One existing file grew that was not a test: `desk/audit/vocabulary.py` gained three
event-type members, grouped and explained beside the ticket that added them. No reason
codes changed — `agent_blocked` and `ceiling_exceeded_for_tier` have been in the
vocabulary since [ADR-0006](../adr/0006-audit-trail-is-a-hash-chained-postgres-table.md)
named them, waiting for this ticket to write to them.
