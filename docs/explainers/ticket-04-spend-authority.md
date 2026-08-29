# Ticket 04 — Spend authority, and the budget that draws down

Fourth in the series. [Ticket 03](ticket-03-mandate-library.md) ended with the Desk able
to prove that a human authorised *something* and that the agent in front of it was the
one allowed to say so. This one is about the gap that leaves.

You can read the first three sections and stop, and you will have the idea.

---

## 1. The situation

Someone tells their assistant: *restock my coffee, keep it under two thousand rupees.*

That single sentence covers a whole errand. Maybe the assistant buys one bag today and
another next week when the good roast is back in stock. Maybe it buys three small bags
instead of two large ones. The person did not mean "spend two thousand rupees once".
They meant "spend up to two thousand rupees, across however many purchases it takes,
and stop".

So the shop on the other end has two problems it has never had before.

The first is **how much is left**. If the assistant comes back a second time, the shop
has to know that seven hundred and fifty rupees of the two thousand are already gone. If
it doesn't, the assistant can spend two thousand rupees as many times as it likes and
every single purchase looks perfectly authorised.

The second is **what the money was for**. "Under two thousand rupees" was said about
*coffee*. It was not permission to spend two thousand rupees on a laptop. But a piece of
paper saying "up to 2000" does not, on its own, know what it was about.

Neither problem is exotic. Both are the kind of thing a human shopkeeper handles without
thinking, by remembering the customer and by having heard the request. A shop serving
software has neither.

## 2. What we built, in plain words

Two things.

**A written-down authorisation with a ceiling and a subject.** The person's device
produces a signed note that says, in effect: *this agent may buy these things, up to
this much, in this currency, between these dates.* Signed, so nobody can forge it or
edit it afterwards.

**A tally the shop keeps.** Every time a purchase actually completes, the shop adds the
amount to a running total for that note. Before agreeing to anything new, it checks the
new amount plus the total so far against the ceiling.

The note never changes. The tally does. That separation is the whole design, and §5
explains why it could not have been the other way round.

## 3. The one thing that is not obvious

Here is the tempting design, and it is wrong.

*Put the remaining balance in the note. Two thousand today; after a seven-fifty
purchase, cross it out and write twelve-fifty.*

It fails immediately, and for a reason that has nothing to do with bookkeeping. The note
is only worth anything **because it is signed**. Signing is what makes it un-forgeable.
The moment you edit a signed document, the signature stops matching, and you have a
worthless piece of paper. To make it valid again you would have to sign it again — and
the only key that can do that belongs to the *person*, sitting in their wallet, which is
exactly where we have gone to great lengths to keep it.

So a note that rewrites itself would need the person's signing key to be somewhere near
the shop's tills. That is the one thing the whole system is built to prevent.

Hence: **the ceiling is in the note; the running total is the shop's own memory.** The
note is read many times and written never.

The pleasing part is that this is not our cleverness. The specification we follow
reaches exactly the same conclusion, and says so normatively — the *verifier* tracks the
accumulated total. We looked it up expecting to be extending the standard and found we
were implementing it.

## 4. The vocabulary, now that you need it

The note is a **mandate**. The person who signs it is the **principal**. The software
doing the shopping is the **buyer agent**. The shop is the **Desk**.

There are actually **two** notes, and that turns out to matter a lot — §6 is about why.
The **open Checkout Mandate** says what may be bought. The **open Payment Mandate** says
what may be spent. *Open* is the specification's word for "the human is not at the
keyboard": what they signed is a set of forward-looking constraints, not one agreed
basket.

A **constraint** is one rule inside a mandate. The ones this ticket reads:

| Constraint | Says |
|:---|:---|
| `checkout.line_items` | which products |
| `payment.budget` | the ceiling: `max` and `currency` |
| `payment.execution_date` | the window: `not_before`, `not_after` |
| `payment.reference` | which Checkout Mandate this budget belongs to |

The running total is the **accumulator**. The standard is **AP2**, Google's Agent
Payments Protocol, version 0.2.

And the sequence of questions the Desk asks about every request is the **trust spine**.
Check 1 was *who is asking*. Check 2 was *did a human authorise this, and is this the
agent they named*. This ticket is **check 3**: *is what is being asked for inside what
was authorised*.

## 5. What check 3 actually does

Five questions. All of them deterministic — no model decides any of them, which is a
rule the whole project runs on and which AP2 states too.

| # | Question | Refusal |
|:--|:---|:---|
| 1 | Do these two mandates belong together? | `category_not_authorised` |
| 2 | Is there a constraint we cannot evaluate? | `category_not_authorised` |
| 3 | Is this the thing that was authorised? | `category_not_authorised` |
| 4 | Is there a ceiling, and is the request in its currency? | `exceeds_remaining_balance` / `category_not_authorised` |
| 5 | Would the payment happen inside its window? | `outside_validity_window` |
| 6 | Is there enough left? | `exceeds_remaining_balance` |

The order is not decoration. The first five are answered from memory; only the sixth
touches the database. Cheap and certain before expensive — the same principle that puts
check 1 before check 5.

Question 2 is the one worth arguing about, so here is the argument. A Checkout Mandate
may carry `checkout.allowed_merchants` — *spend this only at these shops*. We cannot
evaluate it: doing so needs the Desk to have a merchant identity of its own, and nothing
in the system has one yet. The tempting move is to read the constraint, note we can't
check it, and carry on. That would mean a mandate whose person restricted it to a
different shop authorises a purchase *here*.

So it is refused. The rule is one the code already applies elsewhere from the other
direction: a mandate with a constraint **withheld** is refused, because a constraint you
cannot see is one you cannot honour. A constraint you cannot *evaluate* is the same
thing wearing a different coat. The cost is real — a perfectly valid mandate is turned
away until a later ticket can read it — and it is the right way round, because the other
way round spends someone's money at the wrong shop.

Question 4 deserves a note, because at first glance check 2 already did it. Check 2 reads
the mandate's `exp` — when the authorisation *lapses*. Question 4 reads `not_before`,
which is when it *begins*. No expiry date can express *authorised, but not until Monday*,
and a mandate signed on Friday for a payment due next month is an ordinary thing for a
person to want.

## 6. Two notes, not one — and how we nearly got it wrong

The ticket, the product requirements and our own architecture note all said the same
thing: read the ceiling from **the mandate's** `payment.budget` constraint. One mandate.
The one check 2 had already verified.

Before building it, we pulled the specification's own schemas at the exact commit we
pin. They disagree:

```
open_checkout_mandate.json   constraints.items.anyOf → [checkout.allowed_merchants, checkout.line_items]
open_payment_mandate.json    constraints.items.oneOf → [..., payment.budget, payment.execution_date]
```

`payment.budget` is a **Payment** Mandate constraint. Putting one inside a Checkout
Mandate fails that `anyOf` — the mandate would not validate against the schema a
stranger's library holds. And the project's entire differentiating claim is that a judge
can write their own buyer agent, against the published standard, and transact with us
without reading our source. A mandate shape that only we accept would quietly kill it.

So the buyer agent presents two mandates. Which raises the obvious attack: what stops it
pairing a generous budget from one errand with somebody else's shopping list?

The specification already answers that, and it is the neatest thing in this ticket. Every
open Payment Mandate **must** carry a `payment.reference` constraint holding the *digest*
of the Checkout Mandate it was signed for:

```json
{"type": "payment.reference",
 "conditional_transaction_id": "HwzNeGpCaAq4upoQeOmLaSVHdx7E61J6OHS_fs-_fgs"}
```

A digest is a short fingerprint of a document: change one character of the document and
the fingerprint changes completely. So the budget names its shopping list, the person's
signature covers that naming, and mixing and matching stops being possible.

The wallet computes that fingerprint, not the agent. An agent allowed to choose it would
be an agent allowed to choose its own pairing, which is the attack we just closed.

**What this cost.** A bigger ticket than the one that was written: a whole second mandate
reader, check 2 generalised to verify either shape, and four documents corrected. It also
means a buyer agent has to present two credentials rather than one, which is more work
for the counterparty. We took it because the alternative was a standard we only claimed
to follow.

### The fingerprint has to be of the right thing

This is the part of the ticket that took three goes, and it is worth the detour because
the mistake is so easy to make.

The obvious fingerprint is "hash the whole document as it arrived". That is wrong twice
over, and both failures hand a buyer agent free money.

**First, the parts arrive in whatever order the holder likes.** An SD-JWT is a signed
core plus a bag of separately-carried pieces. Which order the pieces go in is nobody's
business but the sender's, and the mandate verifies identically either way — but the
*document* is different text, so it fingerprints differently. Since the ledger is filed
under that fingerprint, an agent with a two-piece mandate gets two ceilings by sending
the pieces the other way round. Google's own SDK emits multi-piece mandates, so this is
not hypothetical.

So: fingerprint the signed core, not the whole document.

**Second — and this is the subtle one — the signature is not part of what it signs.**
It cannot be: it is computed *over* everything else. So the signature can be altered
while the mandate still verifies perfectly. Two ways, both cheap: the last character of
a base64 signature has spare bits that decode to the same bytes, and the ECDSA scheme
itself admits a second valid signature for every one it produces.

Which means one authorisation can be presented under endlessly many "signed cores", each
passing every check, each reading back the same two-thousand-rupee ceiling, and each
opening its own fresh row in the ledger. Two thousand rupees of authority becomes as much
money as the agent has patience.

The fix is to fingerprint **what the signature covers** — the bytes fed to the signing
algorithm, without the signature itself. That is the one part of a mandate nobody but the
principal can change, because changing it is precisely what a signature check catches.

So a verified mandate carries two fingerprints, and they are separate fields on purpose:

| | names | used for |
|:---|:---|:---|
| `digest` | the signed core | matching `payment.reference` |
| `mandate_id` | what the signature covers | filing the running total |

Pairing can safely use the weaker one, because it fails in the safe direction: the
reference sits *inside* the signed budget mandate, so a tampered shopping list stops
matching and the pair is refused rather than accepted.

There is a test for each of these that fails if you swap the fingerprints back.

## 7. Seeing it for yourself

Real output from [`ticket-04-demo.py`](ticket-04-demo.py), which wires up the whole
spine against a real Postgres — enrol a principal, register an agent, sign both
mandates, run checks 2 and 3 — then makes four requests against one two-thousand-rupee
ceiling and one for the wrong thing. Run it yourself:

```
.venv/Scripts/python.exe docs/explainers/ticket-04-demo.py
```

```
A ceiling of 2000.00 INR, drawn down across deals:
  ask   750.00 SKU-COFFEE-1KG    -> authorised, would leave 1250.00 INR
  ask   900.00 SKU-COFFEE-1KG    -> authorised, would leave 350.00 INR
  ask   500.00 SKU-COFFEE-1KG    -> refused: exceeds_remaining_balance
  ask   350.00 SKU-COFFEE-1KG    -> authorised, would leave 0.00 INR

The wrong thing entirely:
  ask    10.00 SKU-LAPTOP-14     -> refused: category_not_authorised

Same mandate still verifies:  True
Same mandate_id as before:    True
Mandate bytes unchanged:      True
What changed is one ledger row: 2000.00 INR of 2000.0 INR spent
```

(The ceiling prints as `2000.0` because that is the scale the mandate's JSON number
carried it at. JSON promises nothing about trailing zeroes, and the trail records the
value that was evaluated rather than a tidier one.)

Read the third line. Five hundred was refused not because five hundred is a lot, but
because sixteen hundred and fifty had already gone. Then three hundred and fifty — a
smaller ask — was authorised, because it fitted. That is a *balance* behaving like a
balance rather than a limit being applied to each request separately, and it is the
behaviour the salami-slicing attack exists to defeat.

And the last three lines are the point of §3: after four deals were drawn against it,
the mandate still verifies and still fingerprints identically. Nothing about the
credential moved. One row in one table did.

## 8. The decisions that cost something

**Evaluating does not reserve anything.** Check 3 reads the tally; it does not add to
it. Only a *closed deal* adds. This is right — an agent that asks about a purchase and
walks away must not burn the person's budget by asking — but it has a real cost: two
requests evaluated a second apart are both told the same remaining balance, and both
could pass, and both could then close.

So the accumulator, not the check, is the arbiter. When a deal closes, `record_spend`
takes the row's lock, re-does the arithmetic against the total as it stands at that
instant, and refuses if it would breach. Check 3 is the fast answer; that is the true
one. Underneath both, the database itself carries a `spent <= ceiling` constraint — if
every line of our Python were wrong, the ceiling a human signed would still hold,
because the row that broke it could not be written. Three layers for one rule, because
it is the rule that has money behind it.

**A mandate with no ceiling is refused.** AP2 makes `payment.budget` optional. A Payment
Mandate without one bounds nothing at all, and we will not read *absent* as *unlimited*.
The cost is honest: we refuse a mandate the specification permits. The asymmetry with
the window is deliberate — an absent *window* still leaves the mandate bounded by its
own expiry, so nothing is unbounded; an absent *ceiling* has nothing behind it.

**A request in the wrong currency is refused, not converted.** A mandate authorising two
thousand rupees does not authorise two thousand of anything else. Converting would mean
holding an exchange rate and manufacturing authority the person never gave. The cost is
that a buyer agent has to ask in the currency it was authorised in.

**The ledger is keyed by what the signature covers, not by the mandate as it arrived.**
This one was found in review, after the first version was written and passing its tests.
A signature has slack in it — base64url leaves spare bits in its last character, and the
signing scheme admits a second valid signature for every one it makes — so one mandate
can be presented sixteen different ways that all verify. The running total had been keyed
by a fingerprint of the whole thing, which meant an agent could reset its own tally by
altering a single character and spend the ceiling again, and again. It is keyed by a
fingerprint of the *signed part* now, which nobody but the person can change. Two
fingerprints where a naive design has one, and the ticket is better for the review that
caught it.

**Money is never a float, anywhere.** Mandate numbers are parsed straight to `Decimal`,
database columns are `numeric`, and an amount always carries its currency. It cost a
small type of our own and a rule that arithmetic across currencies raises rather than
converting. It buys never having to wonder whether a ceiling of `1000.10` is really
`1000.0999999999999`.

**Three different situations refuse under `category_not_authorised`** — a mismatched
pairing, an unauthorised item, and a wrong currency. The set of refusal reasons is
closed on purpose, because a fixed set aggregates into a metric and free text scatters;
growing it means a database migration and a deliberate decision. So these three share a
code and are told apart by the sentence written beside them in the trail. It is the same
compromise check 2 makes, and it is a compromise rather than a design.

## 9. Proving it, rather than asserting it

Every acceptance criterion on the ticket has a test named after it. The interesting ones
are not the happy paths:

- **The ceiling holds with the code taken out of the way.** A test writes directly to the
  database, bypassing every check, and the `CHECK` constraint refuses it.
- **Concurrent closes cannot slip past each other.** Two deals closing at once against
  one mandate, exercising the row lock rather than trusting it.
- **A spend rolls back with the transaction it was recorded in.** A deal that falls over
  after its spend was accumulated leaves no trace of the spend.
- **Evaluating draws nothing down.** Reading a balance opens no row at all, so "has this
  mandate ever been used" stays an answerable question.
- **Both directions against Google's SDK**, for the Payment Mandate as well as the
  Checkout Mandate. A ceiling expressed with their `Budget` model is one we find and
  draw down; a Payment Mandate our wallet signs parses into their constraint models.
  Testing only against ourselves would prove nothing about interoperating.

### Counts actually seen

Run on 2026-08-29 against Python 3.11.9 and an embedded Postgres:

| Environment | Result |
|:---|:---|
| Project venv, no SDK | **179 passed, 1 skipped** |
| Throwaway venv with the SDK | **184 passed** |

The skip is the conformance module, which skips at import when the SDK is absent and
says how to build the environment that runs it — so one skip stands for the five tests
inside it, two of which are new here and exercise the Payment Mandate in both
directions. `ruff check`, `ruff format --check` and `mypy --strict` are clean across all
56 files.

## 10. What this ticket deliberately does not do

| Left out | Who owns it |
|:---|:---|
| Baskets — quantities, and AP2's maximal-flow line-item match | Ticket 08 onward, with the closed mandate |
| Nonce and freshness: is this presentation a replay? | Ticket 05 (check 4) |
| `payment.agent_recurrence` — how *often* a mandate may be reused | Ticket 05, which builds the presentation history it needs |
| Payees, payment instruments, PISPs — how a charge settles | The Razorpay ticket |
| `checkout.allowed_merchants` — is this Desk one of the shops named? | Ticket 08, which gives the Desk its own merchant identity |
| The per-agent ceiling the reputation ladder sets | Ticket 06 |
| Evaluating `checkout.allowed_merchants` — which needs the Desk to have a merchant identity | Not yet owned; refused meanwhile (§5) |
| Actually moving money | Later |

Two deserve a sentence.

**A request is one item, not a basket.** AP2's full `checkout.line_items` rule is a
maximal-flow match over a whole checkout — every requirement satisfied, no item counted
twice. That is the right shape once there is a negotiated basket to match against, which
is the closed mandate a later ticket produces. Check 3 asks the narrower question the
requirements ask: is this the *category* that was authorised.

**Two ceilings are not the same ceiling.** `payment.budget` is what the *principal*
authorised. What a given agent is *trusted* with — by its rung on the reputation ladder,
regardless of what its principal wrote — is a different limit with its own refusal
reason, and it is not built yet.

## 11. The code

| File | What it is |
|:---|:---|
| [desk/spend/check.py](../../desk/spend/check.py) | check 3 — the five questions, and the only part that writes to the trail |
| [desk/spend/accumulator.py](../../desk/spend/accumulator.py) | the running total, and the arbiter when a deal closes |
| [desk/spend/schema.py](../../desk/spend/schema.py) | one table, and the `spent <= ceiling` constraint |
| [desk/spend/money.py](../../desk/spend/money.py) | an amount **and** a currency, never a float |
| [desk/mandate/payment.py](../../desk/mandate/payment.py) | reading the open Payment Mandate: budget, window, reference |
| [desk/mandate/open_mandate.py](../../desk/mandate/open_mandate.py) | what both open mandates share |
| [world/wallet/keys.py](../../world/wallet/keys.py) | the principal's side: signing both mandates, and pairing them |

### Using it

```python
from desk.spend import BudgetAccumulator, Money, SpendAuthorityCheck, SpendRequest

# The wallet signs both, and pairs them itself — the agent never chooses the reference.
checkout = wallet.sign_open_checkout_mandate(...)
payment = wallet.sign_open_payment_mandate(
    principal_id="principal-asha",
    agent_key=agent.public_key,
    for_checkout=checkout,
    constraints=[{"type": "payment.budget", "max": 2000, "currency": "INR"}],
)

# The Desk. Check 2 first, on both.
verified_checkout = check2.verify(checkout, presented_by=identity)
verified_payment = check2.verify_payment(payment, presented_by=identity)

outcome = SpendAuthorityCheck(accumulator, trail).evaluate(
    SpendRequest(item_id="SKU-COFFEE-1KG", amount=Money.of("750.00", "INR")),
    presented_by=identity,
    checkout=verified_checkout,
    payment=verified_payment,
)
outcome.passed          # bool
outcome.remaining       # what closing would leave — a forecast, not a reservation

# Later, when the deal actually closes, in the same transaction as the entry for it:
accumulator.record_spend(verified_payment, amount=amount, conn=conn)
```

The terse contract beside this — the schemas, the refusal table, the trail entries — is
[docs/spend-authority.md](../spend-authority.md).

## 12. Glossary

| Term | Meaning |
|:---|:---|
| **Mandate** | A signed authorisation from a human. Two kinds here. |
| **Open Checkout Mandate** | What may be bought: `checkout.line_items`. |
| **Open Payment Mandate** | What may be spent: `payment.budget`, and the window. |
| **Constraint** | One rule inside a mandate, named by its `type`. |
| **`payment.budget`** | The ceiling: `max` and `currency`. Read from the mandate, never from our own configuration. |
| **`payment.reference`** | The digest naming which Checkout Mandate a budget belongs to. |
| **Accumulator** | The Desk's running total per mandate. The only thing that changes. |
| **Digest** | A short fingerprint of a document; changes completely if the document does. |
| **Spend ceiling** | What a mandate authorises in total. Distinct from the ladder's per-agent ceiling. |
| **Check 3** | Spend authority. Is what is being asked inside what was authorised? |

---

## 13. Next

**Ticket 05 — check 4, replay and freshness.** Everything so far has a hole in it that
this ticket makes worse rather than better: a request that passes checks 1, 2 and 3
passes them again if you send it a second time. The tally stops a *replayed deal* from
exceeding the ceiling, which is real — but it does not stop the same presentation being
replayed, and it does not stop a mandate being presented long after the moment it was
meant for.

That needs a nonce the Desk remembers and a freshness window, and both live on a layer
we have deliberately refused to read so far: the key-binding hop at the end of the
presentation, which is where `nonce` and `aud` sit.
