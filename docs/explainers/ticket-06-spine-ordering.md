# Ticket 06 — The order of the questions

*Sixth in the series. [Replay and freshness](ticket-05-replay-and-freshness.md) came
before it, and this one assumes nothing from the five before it beyond a sentence of
recap each.*

Four checks already existed, each built and tested on its own. This ticket adds almost
no new logic at all. What it adds is the **order they run in**, and the rule that the
first *no* ends the conversation — which turns out to be the part with the most
security in it.

---

## 1. The situation

Think about a security desk in the lobby of a building, and the questions the person
behind it asks a visitor.

*Is that really your ID card?* — takes two seconds, and the answer is certain.
*Does your name appear on today's visitor list?* — takes ten seconds, and the answer is
certain. *Does the letter you are carrying actually authorise you to collect the thing
you say you are collecting?* — takes a minute of reading, and the answer is mostly
certain. *Is this person behaving oddly?* — takes judgement, takes time, and the answer
is never certain.

Now imagine the desk asks them in the opposite order. Somebody walks in with a forged
ID, and the guard spends five minutes studying their body language, forming an opinion
about a person whose identity was fake the whole time. The opinion is worse than
useless: it was formed about a fiction, and forming it cost five minutes that a
two-second glance at the card would have saved.

That is the entire idea. **Cheap and certain first; expensive and uncertain last.** Not
because it is faster — though it is — but because the uncertain questions should never
be asked about traffic that the certain ones would have thrown out.

There is a second rule, and it is the one people forget. When the guard finds the forged
ID, they **stop**. They do not go on to check the visitor list "for completeness". If
they did, the day's log would end up recording an opinion about a person the desk had
already turned away — and the log is the thing anyone reads afterwards.

## 2. What we built, in plain words

A single front door, and behind it the four questions in a fixed order:

1. **Is this really from who it says?** (a signature)
2. **Did a human authorise it, and this particular assistant?** (a signed authorisation)
3. **Is what is being asked for inside what was authorised?** (an item, a price, a
   ceiling)
4. **Is this happening now, and only once?** (a timestamp and a one-off value)

An external assistant hands the Desk one signed string. That string is the only thing it
can do — there is no other way in. The Desk works down the list, writes down what each
question concluded, and the moment one of them says no it stops and answers.

Read that back afterwards and you get a sentence of the form *this was turned away at
question three, because the mandate authorises coffee and it asked for a laptop* — and,
just as importantly, *questions four and five were never asked*. Not "we also checked
those and they were fine". Never asked.

## 3. The one thing that is not obvious

Ordering looks like a performance decision. It is presented as one everywhere you will
read about it — do the cheap thing first, save the expensive call. That is true here and
it is the least interesting thing about it.

Two sharper reasons.

**A judgement formed about a fake is not neutral, it is harmful.** Question four in our
list — is this happening now — is answered by *spending* something. When the Desk accepts
a handover it writes down the one-off value that came with it and refuses to honour that
value ever again. The value is used up. So if the Desk answered "is this fresh?" before
"is this within budget?", then anyone who could get a request refused for the wrong item
could make an honest assistant burn its one-off values on requests that were never going
to succeed. The cheap check protects the expensive one *and* protects the honest
counterparty from it.

**Later, one of these questions costs real money.** Check 5, which is not in this ticket,
asks a language model whether the text in a request is trying to manipulate the Desk.
That is a paid call taking a second or two. Running it on a request whose signature does
not verify is not merely wasteful — it is a paid opinion about a message from nobody.

And the flip side, which is the design pressure worth naming before somebody proposes
it: **a trusted counterparty does not get to skip the cheap checks.** Reputation, which
arrives later, decides *how much* an assistant may do. It never decides *whether* the
certain questions get asked. Inverting that would be the whole model collapsing into a
name-based one.

## 4. The vocabulary, now that you need it

- **Desk** — our system. The merchant that sells to machines.
- **Buyer agent** — the external assistant asking to buy. Untrusted, always.
- **Mandate** — the human's signed authorisation. AP2 splits it in two: a **Checkout
  Mandate** saying what may be bought, and a **Payment Mandate** saying what may be
  spent.
- **Presentation** — a mandate as it arrives, with a **proof of possession** attached:
  the assistant's own signature saying *I am handing this to you, now*.
- **Nonce** — the one-off value on that proof. Honoured once per agent, ever.
- **Trust spine** — the four checks, in order. The name is the point: it is a spine
  because everything else hangs off it.
- **Short-circuit** — stopping at the first refusal, and running nothing after.
- **Reason code** — the named refusal, drawn from a closed set so refusals aggregate
  into a metric instead of scattering into free text.
- **Audit trail** — the append-only, hash-chained record every check writes to.

## 5. What the spine actually does

One method, `TrustSpine.receive`, taking one signed string.

| Position | Check | Asks | Refuses with |
|---:|:---|:---|:---|
| 1 | identity | does this signature verify against a registered key? | `agent_signature_invalid` |
| 2 | mandate validity | did the principal sign this, is it in date, does it name this agent? | `mandate_signature_invalid`, `mandate_expired`, `agent_mandate_mismatch` |
| 3 | spend authority | right item, right currency, inside the window, inside the ceiling? | `category_not_authorised`, `outside_validity_window`, `exceeds_remaining_balance` |
| 4 | replay and freshness | fresh proof of possession, nonce never seen? | `request_stale`, `nonce_replayed` |

A wholly valid request leaves **six** entries in the trail rather than four, because
checks 2 and 4 each run twice — once per mandate. AP2 splits the authorisation, and
RFC 9901 binds a proof of possession to exactly one presentation, so two mandates means
two proofs and two verdicts. Both runs sit at the same position, and a refusal in either
is a refusal at that position.

One consequence falls out of that and is worth an agent author's attention: **the two
proofs must carry different nonces.** The Desk honours a nonce once per agent, so a
request that reuses one across both mandates replays itself and has its own second half
refused. That is a real cost of scoping nonces per agent rather than per presentation,
and the fix on the agent's side is one line.

## 6. The nine refusals, and the one with no code of its own

The four checks between them own nine named refusals, and a reason code nothing can
reach is a reason code that does not exist. Each of the nine has a test that builds a
wholly valid request, changes exactly one thing, sends it through the front door, and
asserts on the reason and the position.

There is a tenth case with no code of its own, and where it landed took the longest to
settle. What should the Desk do with a request that is **validly signed and is not a
purchase request at all** — no mandate in it, or no price?

The tempting answer is a new family of protocol refusals in front of the spine. We did
not do that, because it would mean two vocabularies saying nearly the same things in
different words, and a reader of the trail having to learn both. Instead the spine reads
the request **leniently**: a missing field becomes the emptiest value of its kind, and
the check that would have read it refuses it.

- No mandate becomes an empty mandate, and check 2 says *nothing here establishes that a
  human authorised anything*.
- No item becomes an empty item id, and check 3 says *the mandate does not authorise
  that*.
- No price has nowhere to go, because **there is no emptiest amount of money** — zero is
  a number a mandate would happily authorise. So this one case the spine refuses itself,
  at check 3's position and under check 3's reason code, with the sentence *an unreadable
  price is not a free one*. It is the exact mirror of the refusal check 3 already writes
  for a mandate that sets no ceiling: the Desk does not read an absent bound as an
  unlimited one.

A price is two fields, an amount and the currency it is in, and either one being missing
or malformed leaves the same nothing — so the refusal names both and the evidence shows
what arrived in each. That matters more than it sounds: a refusal saying the amount was
missing when it was the currency that was unreadable is a true verdict with a false
sentence attached, and the sentence is the product here.

## 7. Seeing it for yourself

One registered agent, one principal, one pair of mandates. The first request is wholly
valid; each of the others is that same request with exactly one thing changed.

```
.venv/Scripts/python.exe -m pytest tests/spine/test_explainer_walkthrough.py -s
```

```
One agent, one principal, one pair of mandates:
  a valid request          -> passed                                               (ran: 1 2 2 3 4 4)
  a forged signature       -> refused at check 1: agent_signature_invalid          (ran: 1)
  somebody else's mandate  -> refused at check 2: agent_mandate_mismatch           (ran: 1 2)
  the wrong item           -> refused at check 3: category_not_authorised          (ran: 1 2 2 3)
  that first request again -> refused at check 4: nonce_replayed                   (ran: 1 2 2 3 4)
```

Read down the last column, which is the whole ticket. The refusal moves one place
further along each time, and nothing after it ever runs.

Two lines repay a second look. **`somebody else's mandate`** is a genuine mandate,
genuinely signed by the principal, presented by an agent that genuinely holds the key it
registered — it is simply not the key the mandate names. That is what a stolen mandate
looks like, and it is why stealing one is not enough. **`that first request again`** is
the identical bytes of the request that passed a moment earlier. Nothing about it is
false. Sending it twice is not lying; it is repeating, and repeating is enough to buy
the coffee twice.

## 8. The decisions that cost something

**The order is written down once, and the spine checks its own work against it.** There
is a constant naming the four positions, and an outcome refuses to exist describing a
run that skipped one or ran them out of sequence. That guard costs a little ceremony on
every request and duplicates something a careful reader could see by reading the method.
It is there because every other test in this suite asserts *outcomes*, and a refactor
that swapped two checks would keep almost all of them passing.

**Check 4 runs last, and that spends nonces later than it could.** Running it beside
check 2 would refuse replayed traffic sooner and cheaper. We do not, because a nonce
spent is spent for ever, and a request refused at check 3 must not cost the honest agent
its presentations. The cost is that a replay of an unaffordable request does more work
before being refused than it strictly needed to.

**Leniency in reading the request, rather than a second refusal vocabulary.** The cost is
real: a request with a typo in a field name is refused as though it named no mandate,
which is a slightly blunter answer than the truth. What is bought is one vocabulary in
the trail instead of two, and no path by which a malformed request produces a refusal
that no check actually made.

**One nonce per presentation, not one per request.** Simpler, and strictly stronger, and
it means an agent presenting two mandates must mint two nonces. The alternative — scoping
a claim by nonce *and* the presentation it was made over — would let one nonce cover a
whole request, at the cost of a wider key in the store built in ticket 05. If a
verifier-issued challenge arrives with the protocol boundary in ticket 30, this is worth
revisiting.

**Request bodies are now parsed with exact decimals.** AP2 types money as a JSON number,
so a conformant agent may well write `1000.10` — and read as a float that is not
1000.10. Mandate claims were already parsed this way; requests now are too. It is a
one-line change in a module this ticket otherwise does not touch, and the alternative
was refusing every honest agent that wrote a number instead of a string.

## 9. Proving it, rather than asserting it

Every acceptance criterion has a test named after it. The ones worth calling out are the
ones that are not criteria:

- **A check-3 refusal leaves the agent's nonces unspent.** The same two nonces are sent
  again in a corrected request, and it passes. Had check 4 run first, this would come
  back a replay.
- **The spine will not record a run that skipped a check, or one that stopped early.**
  Driven directly, because no request can reach either: an outcome built from a check-1
  entry and a check-4 entry raises, and so does one that reports passing having only
  reached check 3. The second is the shape a refactor that dropped the freshness loop
  would produce, and it is in order and gapless — every ordering test would still pass.
- **A validly signed request that is not a purchase request** is refused at check 2, and
  checks 3 and 4 leave nothing.
- **A price of `1000.10` on the wire is `1000.10` in the Desk**, written as a JSON number
  rather than a string, and never routed through a float.
- **A currency of `"inr"` is refused, and the record says which half it could not read.**
- **`"amount": true` is not an offer of one rupee.** A `bool` is an `int` in Python, and
  an unguarded reader would take it for one.
- **No model call happens anywhere in checks 1 to 4**, which is the claim this whole
  design rests on. It is asserted two ways rather than promised: every module the spine
  is built from has its imports parsed and compared against a closed list with no HTTP
  client and no model SDK on it, and a real request is driven through while watching what
  Python loads. A third test asserts that the list of spine packages is still the list of
  packages under `desk/`, so adding `desk/inspector/` in ticket 10 forces the decision to
  be made rather than skipped.

### Counts actually seen

Run on 2026-08-30 against Python 3.11.9 and an embedded Postgres:

| Environment | Result |
|:---|:---|
| Project venv, no SDK | **256 passed, 1 skipped** |
| Throwaway venv with the SDK | **261 passed** |

Thirty-one of those are new here: eighteen on the refusal reasons, nine on the order and
the short-circuit, three on the absence of a model call, plus the walkthrough above.
The skip is the conformance module, which skips at import when Google's AP2 SDK is
absent and says how to build the environment that runs it. `ruff check` and
`mypy --strict` are clean across all 79 files.

## 10. What this ticket deliberately does not do

| Left out | Who owns it |
|:---|:---|
| Check 5 — content inspection, in either half | Ticket 10 |
| An HTTP or A2A boundary in front of `receive` | Ticket 30 |
| A request identifier tying one run's entries together | Ticket 30 — see below |
| Computing spend ceilings or scrutiny tiers | Tickets 11 and 12 |
| Negotiation, settlement, procurement | Tickets 08, 09, 14 |
| Rate limiting or abuse controls beyond the named checks | Not owned |

One deserves a sentence. **Nothing in the trail says which entries belong to which
request.** Within a process the outcome hands back exactly the entries its own run
wrote, which is enough for everything here; but two agents transacting at once produce
one interleaved sequence, and telling them apart afterwards means filtering by agent.
A request identifier is the fix, it touches every check's payload, and it belongs with
the protocol boundary that will mint one.

## 11. The code

| File | What it is |
|:---|:---|
| [desk/spine/spine.py](../../desk/spine/spine.py) | the order, the short-circuit, and the self-check against both |
| [desk/spine/request.py](../../desk/spine/request.py) | what a purchase request contains, and how leniently it is read |
| [desk/identity/check.py](../../desk/identity/check.py) | check 1 |
| [desk/mandate/check.py](../../desk/mandate/check.py) | check 2 |
| [desk/spend/check.py](../../desk/spend/check.py) | check 3 |
| [desk/freshness/check.py](../../desk/freshness/check.py) | check 4 |
| [world/agents/keys.py](../../world/agents/keys.py) | the agent's side: `request_purchase`, which builds and signs one request |

### Using it

```python
from desk.spine import TrustSpine

spine = TrustSpine(
    IdentityCheck(registry, trail),
    MandateCheck(principals, trail),
    SpendAuthorityCheck(BudgetAccumulator(pool), trail),
    FreshnessCheck(NonceStore(pool), trail),
    trail,
)

outcome = spine.receive(signed_request)
if outcome.passed:
    ...                     # outcome.remaining is what closing this deal would leave
else:
    print(outcome.refused_at, outcome.reason_code)
```

And the agent's side, which is all an external one can do:

```python
request = agent.request_purchase(
    agent_id=identity.agent_id,
    checkout=agent.present(checkout_mandate, audience="stitchai-desk"),
    payment=agent.present(payment_mandate, audience="stitchai-desk"),
    item_id="SKU-COFFEE-1KG",
    amount="750.00",
)
```

## 12. Glossary

| Term | Meaning |
|:---|:---|
| **Trust spine** | Checks 1 to 4, run in a fixed order over one request |
| **Short-circuit** | Stopping at the first refusal, and running nothing after it |
| **Position** | Which of the four a run reached, 1 to 4 |
| **Presentation** | A mandate plus the proof of possession handing it over |
| **Nonce** | The one-off value on that proof; honoured once per agent |
| **Reason code** | The named refusal, from a closed set |

## 13. Next

Ticket 07 builds the catalogue and margin computation, and ticket 08 the negotiation
that a request passing this spine is handed to. Ticket 10 adds check 5 — the first
question in the sequence whose answer is not certain, and the reason the four before it
are ordered the way they are.
