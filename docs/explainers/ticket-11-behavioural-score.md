# Ticket 11 — Noticing when an agent stops acting like itself

*Ticket 11 of the StitchAI build. The ticket before it read one message for hidden
instructions. This one reads a whole sequence of requests for a change of character.*

Read the sections in order and stop wherever you have what you need. The first three
have no jargon in them; the code is at the end.

---

## 1. The situation

Some bad behaviour does not live in any single request.

A buyer's software registers properly, presents a valid authorisation, stays well
inside its budget, and buys a small bag of coffee. Then it does that again. And again,
forty times over two weeks, every one of them clean. Then it asks for something forty
times larger.

Every individual request in that story passes every check. The identity is real. A
human authorised the category. The amount is inside the ceiling. The timing is fine.
There is nothing to refuse — until you stop looking at the request and look at the
*run* of requests, and notice that the last one does not belong with the others.

That pattern has a name — **trust farming** — and it has cousins: a spend that creeps
up a little each time, a sudden burst of requests seconds apart, an agent that has only
ever bought coffee abruptly buying across six categories. None of them is visible one
request at a time.

This ticket builds the part of the Desk that watches the sequence.

---

## 2. Against its own history, not against a list of attacks

There is an obvious way to build this and it is the wrong one.

The obvious way: collect examples of trust farming, escalation, probing; label them;
train a classifier to recognise them. It is tempting because the labels look free — the
project generates its own population of test buyers, so it knows which ones are
adversarial.

The problem is that those labels are *ours*. A detector trained on them learns to spot
the attacks we thought of. The whole point of the honest-metrics design
([ADR-0009](../adr/0009-behavioural-detection-is-unsupervised-and-per-agent.md)) is a
set of attack types held back during development and run only at the end — and a
detector that has been shown a taxonomy will do well on that taxonomy and badly on
anything outside it, which is exactly the weakness the held-out set exists to expose.

So this works the other way round. It has **no examples of attacks in it at all**. For
each agent it builds a picture of what that agent normally does, and scores each new
request by how far it departs from *that agent's own* normal. "Unlike itself"
generalises to attacks nobody wrote down. "Like attack #7" does not.

A nice consequence: there is nothing to keep up to date. No attack database, no
signatures, no retraining when a new trick appears.

---

## 3. Five signals, and what each one is really watching

For every request, five numbers are computed. Each is zero when nothing is unusual and
grows as the request departs from the agent's baseline.

**Amount, against its own recent average.** If an agent's requests have been averaging
600 rupees and this one is 3,000, that is a departure. Not because 3,000 is a lot —
for a different agent it might be normal — but because it is a lot *for this one*.

**Amount, against its own highest ever.** This is the trust-farming tell specifically.
The average moves slowly as small requests pile up; the ceiling does not move at all.
An agent that has never once exceeded 600 and suddenly asks for 3,000 has blown
straight through its own ceiling, and that shows up here even when the average has been
dragged around.

**Timing, against its own rhythm.** An agent that usually sends a request every few
hours and suddenly sends three in ten seconds is doing something different. Probing
comes in bursts. (Requests that arrive a few milliseconds apart are ignored here —
that is a batch, not a burst, and "faster than a rhythm measured in milliseconds" is
not a meaningful idea.)

**Categories, against what it has bought before.** An agent that has only ever bought
coffee, then buys a laptop, then a monitor, then a chair, is ranging outside its
established behaviour. An agent that has always bought a bit of everything scores low
here, because nothing is new to it.

**Refusals, lately.** How often this agent has been turned down in its recent history.
A run of near-misses — requests that almost worked — is itself a signal, and it
accumulates rather than resetting after each one.

The five numbers are added up with weights, and if the total crosses a threshold the
request is refused with the reason `escalation_pattern_detected`.

**The weights and the threshold are tuning. The five signals and the "against its own
baseline" idea are the design.** Someone will retune the weights; that is fine and
expected. What must not change is that the score is relative to the agent's own past.

---

## 4. Where it sits

This is the second half of check 5. The first half (the previous ticket) is the
Inspector, which reads one message's text. This half reads the request history. They
run at the same point — after checks 1 to 4 have passed — and both obey the same hard
rule:

> **Check 5 can only refuse. It has no way to grant anything.**

The score is a number, and it is tempting to imagine using it in the other direction —
"this agent has a long clean history, let it skip a check". That inverts the security
model ([ADR-0005](../adr/0005-check-five-can-only-refuse.md)). The outcome this half
produces carries the score and the five signals and *nothing that could be read as
permission* — no identity, no ceiling, no balance. A test fails if anyone ever adds
such a field.

Two more things shape when it fires:

**A new agent is not scored.** You cannot depart from a baseline you do not have. Until
an agent has made a handful of requests, the score is reported as zero and the entry
says it was sample size, not calm, that produced the pass.

**Scrutiny tier moves the bar.** A brand-new agent is watched closely and its drift is
caught sooner; an agent at the top of the reputation ladder is given more room before
the same score counts against it. The tier arrives as context — computing it is the
reputation ladder's job, a later ticket. This ticket only *consumes* the tier and, for
now, uses it to scale the threshold.

---

## 5. What it costs

Almost nothing, computationally — this is arithmetic over a list, no model, no network,
no new storage. The history is read straight back out of the audit trail, which
already records every check of every request. One source of truth, not two.

The real cost is elsewhere, and it is honest to name it:

**A relative baseline can be gamed by being patient.** An attacker who is willing to
spend weeks establishing a *genuinely* varied, high-value pattern can make a large
request look normal — because for that agent, it now is. This half does not claim to
stop that. What stops it is that the ceiling on how fast an agent's spending limit can
rise is set by the reputation ladder, not by this score, and that ladder has a minimum
time on each rung. This check makes farming expensive and visible; the ladder makes it
slow.

**Thresholds are judgement calls.** Set the bar too low and ordinary buyers who change
their habits get refused; too high and a patient attacker slips under it. The tests
here deliberately assert only *ordering* — a departure scores above calm — and never a
specific number, because a test that locked in a number would have to be "fixed" every
time the bar moved, and that is how a number nobody chose ends up load-bearing.

---

## 6. Watching it happen

Four agents, four shapes of history, the same scoring function. This is the output of
`tests/inspector/test_behaviour_walkthrough.py`, asserted rather than described, so it
cannot drift without the suite noticing.

```
Four agents, four shapes, one score (threshold 1.50 at standard scrutiny):
  steady           score  0.03  -> passed
  escalating       score  3.49  -> refused
  trust farming    score  9.60  -> refused
  probing          score  2.50  -> refused
```

- **steady** — a dozen requests, same product, similar amounts, an even rhythm. The
  score is basically noise. This is the shape every honest agent has.
- **escalating** — the amount climbs every request, each step bigger than the last. By
  the last one it is far enough above the agent's own recent average to be refused.
- **trust farming** — eleven identical small requests, then one five times larger. The
  average barely moved; the *ceiling* was smashed. That is the signal that carries it.
- **probing** — every amount identical, so the amount signals are zero. What trips it
  is timing: a settled ten-minute rhythm, then three requests three seconds apart.

The steady agent is the control. If a weight is ever tuned so hard that it starts
refusing steady, this table changes and the test fails.

---

## 7. What this ticket deliberately does not do

- **It does not use attack labels.** Not now, not "later to improve accuracy on the
  development set". That would defeat the held-out evaluation
  ([ADR-0009](../adr/0009-behavioural-detection-is-unsupervised-and-per-agent.md)).
- **It does not move a trust score or a rung.** It emits a refusal and a score. Turning
  that score into reputation change is the next ticket.
- **It does not compute the scrutiny tier.** The reputation ladder does.
- **It does not grant anything.** A long clean history buys more room before the bar,
  through the tier — it never buys a skipped check.
- **It is not a learned model.** It is a weighted sum of five deterministic signals. If
  a learned model ever earns a place here it is a sequence model over request
  histories, still trained without attack labels — that is a later question and this is
  the baseline it would have to beat.
- **It does not read the message text.** That is the other half of check 5, the
  previous ticket.

---

## 8. The vocabulary, now that you need it

- **Behavioural score** — the number this ticket computes: how far an agent's latest
  request departs from its own recent pattern.
- **Signal** — one of the five inputs to the score: amount vs mean, amount vs ceiling,
  interval speed-up, category churn, refusal rate.
- **Baseline** — what an agent normally does, formed from its recent request history.
  Per-agent, and "recent" on purpose — a month-old habit does not vote.
- **Trust farming** — building a clean record with small requests, then attempting a
  disproportionate one. The score's amount-vs-ceiling signal is aimed at it.
- **Escalation** — spend that rises request by request. The reason code is
  `escalation_pattern_detected`.
- **Scrutiny tier** — how closely check 5 watches an agent. Three levels, consumed
  here, computed by the reputation ladder later.
- **Unsupervised** — no examples of attacks in the model. It learns each agent's
  normal, not a catalogue of abnormal.

---

## 9. Where the code lives

```
desk/inspector/history.py      one agent's past requests, parsed back out of the trail
desk/inspector/behaviour.py    the five signals, the weighted score, and the check
desk/audit/vocabulary.py       two new event types: check_5_behaviour_passed / _refused
```

`history.py` is the seam between "the trail" and "a list of requests". It walks an
agent's entries, groups them into one record per request (when, what, how much, was it
refused), and hands `behaviour.py` a clean list to do arithmetic over. Keeping that
parsing in one place means the score never has to know the trail's shape.

The two new event types are a deliberate addition to a closed vocabulary. Check 5's two
halves get separate members — `check_5_inspection_*` for the Inspector,
`check_5_behaviour_*` for this — rather than one shared member with a flag, because the
control room subscribes by event type, and "an escalation pattern was seen" is a
different thing on screen from "that message was an injection".

---

## 10. If you want to read the code

Start with `desk/inspector/behaviour.py` — the module docstring lists the five signals
and the one rule. Then `score_history`, which is a pure function: a list of requests in,
a score out, no database.

The tests are the other way in. `tests/inspector/test_behaviour_score.py` feeds
`score_history` the four named shapes and asserts only that a departure scores above
calm — never a specific number. `tests/inspector/test_check_five_behaviour.py` builds a
history by sending real signed requests through `TrustSpine.receive`, so the trail it
reads back is the one a running Desk would have, then checks that a disproportionate
request after a calm history is refused with `escalation_pattern_detected`.
`test_check_five_behaviour.py::test_a_behaviour_outcome_carries_nothing_that_could_grant_anything`
is the guard on ADR-0005.

**Counts, actually run:** 45 tests in `tests/inspector/` (46 collected, one skipped) —
Ticket 10's 27 for the Inspector plus Ticket 11's 18: 10 the score on synthesised
histories, 7 the wiring through the front door, 1 the walkthrough. 504 in the suite as
a whole, plus three skipped — the AP2 conformance test, ticket 09's Razorpay test, and
ticket 10's real-Inspector corpus test.

Two existing files grew. `desk/audit/vocabulary.py` gained two event-type members, with
the reason recorded beside them (no reason codes changed — `escalation_pattern_detected`
has been in the vocabulary since ADR-0006 named it). `desk/audit/trail.py` gained a
`most_recent` option on `query`, which takes the last N matching entries in the
database rather than reading an agent's whole history to keep a handful — the tail
this check needs.
