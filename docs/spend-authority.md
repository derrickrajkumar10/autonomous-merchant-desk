# Spend authority and the budget accumulator (check 3)

Check 2 proved a human authorised *something*. This is where the authorisation is
finally read for what it says:

> A mandate to buy two kilos of coffee under 2,000 rupees is a perfectly valid mandate
> to present when asking for a laptop. Check 2 passes it.

This document is the contract an external buyer agent codes against: what it has to
present, what the Desk checks, and what it refuses. The reasoning a newcomer wants is
in [the explainer](explainers/ticket-04-spend-authority.md).

Decisions behind it: [ADR-0004](adr/0004-partial-spend-is-desk-side-ledger-state.md) for
why the running total is Desk-side state. Field-level citations are in
[the research note](research/ap2-mandate-model.md) §1a and §1c.

---

## Two mandates, not one

AP2 v0.2 splits the authorisation in two, and so do we:

| Mandate | `vct` | Says |
|:---|:---|:---|
| Open **Checkout** Mandate | `mandate.checkout.open.1` | What may be **bought** |
| Open **Payment** Mandate | `mandate.payment.open.1` | What may be **spent** |

The split is the specification's, not a preference. `payment.budget` is a Payment
Mandate constraint, and the open Checkout Mandate's schema restricts its array to
checkout constraints:

```
open_checkout_mandate.json   constraints.items.anyOf → [checkout.allowed_merchants, checkout.line_items]
open_payment_mandate.json    constraints.items.oneOf → [..., payment.budget, payment.execution_date, payment.reference]
```

A ceiling carried inside a Checkout Mandate would not validate against the schema a
stranger's library holds, so a mandate shaped that way would not interoperate — which
is the entire reason for adopting a standard.

### How the two are paired

By digest, and the specification does the pairing itself. One `payment.reference`
constraint is **mandatory** on the Payment Mandate (the schema's `contains` rule) and
carries the digest of the Checkout Mandate it was signed for:

```json
{"type": "payment.reference",
 "conditional_transaction_id": "HwzNeGpCaAq4upoQeOmLaSVHdx7E61J6OHS_fs-_fgs"}
```

The digest is taken over the mandate's **issuer JWS**, under the `_sd_alg` of the
mandate the constraint sits in — AP2's own rule (`docs/ap2/payment_mandate.md:231-235`)
fixes the algorithm but not the input. Not over the presentation as received: the
disclosures are a *set*, and their order on the wire is the holder's to choose, so two
presentations of one signed mandate would otherwise digest differently.

"The SD-JWT this constraint is in" is the **Payment** Mandate, so that is the algorithm
the comparison digest is taken under — recomputed over the Checkout Mandate presented,
rather than reusing whichever digest check 2 happened to take of it. The two mandates
are not required to agree on an algorithm: requiring it would refuse a conformant pair,
and refuse it under a sentence about the wrong checkout, which would not be true.

### The other digest, and why the ledger uses it instead

A verified mandate comes back with two digests, and they are separate fields because
mixing them up is a spending hole.

| | `digest` | `mandate_id` |
|:---|:---|:---|
| Taken over | the issuer JWS | the JWS **signing input** (`header.payload`) |
| Answers | *which mandate is this?* | *which authorisation is this?* |
| Used for | matching `payment.reference` | keying the accumulated spend |

A JWS is `header.payload.signature`, and **the signature is not part of what it
covers**. It can therefore be varied while the mandate still verifies: base64url leaves
spare bits in the last character of a 64-byte ECDSA signature, and ECDSA admits a second
valid signature for every one it produces. So one signed mandate can be presented under
many issuer JWSs, every one of which passes check 2 and reads back the same ceiling.

That is fatal for anything keying *state*. A running total keyed by a digest the holder
can vary is a running total the holder can reset, and 2,000 rupees of authority becomes
as much money as the holder has patience. So the ledger keys on the signing input, which
is the one part of a mandate that cannot be altered without the alteration being exactly
what a signature check catches.

Pairing stays safe under the weaker digest because it fails closed: `payment.reference`
sits inside the *signed* Payment Mandate, so a mangled Checkout Mandate stops matching
and the pair is refused rather than accepted.

`mandate_id` is distinct per issuance as well as per authorisation — the signing input
carries freshly salted disclosure digests — so a principal who signs the same
constraints twice gets two mandates with two ceilings. Which is right: they authorised
twice.

**The wallet computes the reference, never the agent.** `sign_open_payment_mandate`
takes the checkout mandate itself and digests it. An agent that chose the reference
could pair a generous budget with somebody else's shopping list.

## The constraints check 3 reads

| Constraint | On | Required | What it gives |
|:---|:---|:---|:---|
| `checkout.line_items` | Checkout | yes (schema) | The item ids authorised |
| `payment.reference` | Payment | yes (schema) | Which checkout this pays for |
| `payment.budget` | Payment | **yes, by us** | `max` and `currency` — the ceiling |
| `payment.execution_date` | Payment | no | `not_before` / `not_after` |

Two of those rows are ours rather than AP2's and both are stated here because they are
deviations someone should be able to find:

- **A Payment Mandate with no `payment.budget` is refused.** AP2 leaves the constraint
  optional. A mandate without one bounds nothing, and the Desk will not read *absent*
  as *unlimited*. The asymmetry with the window below is deliberate: an absent window
  still leaves the mandate bounded by its own `exp`, which check 2 reads. Nothing
  bounds an absent ceiling.
- **An absent `payment.execution_date` constrains nothing**, which is ordinary
  constraint semantics.

The other five payment constraint types AP2 defines — payees, payment instruments,
PISPs, `payment.amount_range`, `payment.agent_recurrence` — are carried through in
`constraints` and **not evaluated**. The first three constrain how a charge settles
(the Razorpay ticket); `agent_recurrence` needs the presentation history check 4
builds.

### Money

`payment.budget.max` is a JSON `number` and AP2's own example is `1000.00`, so it is a
decimal amount in the currency's **ordinary units** — rupees, not paise. Its sibling
`payment.amount_range.max` is an integer in minor units instead. That inconsistency is
inside the specification; the research note §1c records it. The Desk works in the units
the mandate was written in and converts nowhere — turning rupees into paise is the
payment rail's job, at the point a charge is created.

Amounts are `Decimal` end to end. Mandate claims are parsed with `parse_float=Decimal`,
so a ceiling never becomes a float on the way in, and `numeric` columns come back as
`Decimal` on the way out. A `Money` is an amount **and** a currency; arithmetic across
two currencies raises rather than converting.

One honest wrinkle: a wallet that serialises `2000.00` through a Python float emits
`2000.0` on the wire, and the trail then reads `2000.0 INR`. The number is exact and
identical either way — only the trailing zero is lost, and it is lost in the wallet
before signing, not anywhere in the Desk.

## What check 3 decides

Five questions. The four the Desk can answer from memory run before the one that reads
state, which is the only reason the order is what it is.

| # | Question | Refusal |
|:--|:---|:---|
| 1 | Does the Payment Mandate reference *this* Checkout Mandate? | `category_not_authorised` |
| 2 | Does the Checkout Mandate restrict its merchants? | `category_not_authorised` |
| 3 | Is the item among the authorised `acceptable_items`? | `category_not_authorised` |
| 4 | Is there a ceiling, and is the request in its currency? | `exceeds_remaining_balance` / `category_not_authorised` |
| 5 | Would the payment execute inside `not_before`…`not_after`? | `outside_validity_window` |
| 6 | Is the amount plus the accumulated total at or under `max`? | `exceeds_remaining_balance` |

Question 2 is a **refusal to guess**. `checkout.allowed_merchants` is a constraint AP2
defines and the Desk cannot yet evaluate — doing so needs a merchant identity of its own,
which nothing here models. Reading it and carrying on would let a mandate whose principal
restricted it to another merchant authorise spending here, so a mandate that sets it is
refused instead. It is the same rule the disclosure handling already applies from the
other side: `sdjwt._resolve` refuses a mandate with a constraint *withheld*, and this
refuses one with a constraint *unevaluated*. Honouring a mandate by ignoring part of what
it says is not honouring it.

The cost is stated plainly: a conformant mandate carrying that constraint is refused until
a later ticket can evaluate it.

Four distinct situations land on `category_not_authorised`, and they are grouped here
rather than given codes of their own because the reason set is closed (ADR-0006) and
the PRD lists two reasons for this check. Growing the vocabulary is a deliberate act
with a database migration behind it; the specific sentence is in the trail entry
either way. The four: a mismatched pairing, a merchant restriction the Desk cannot
evaluate, an unauthorised item, and a request in a currency the mandate never
authorised. The last is a refusal rather than a conversion
because the Desk holds no exchange rate, and inventing one would manufacture authority
the principal never gave.

Structural problems — a malformed budget, a window that ends before it begins, two
ceilings in one mandate — never reach check 3. They are refused in check 2 under
`mandate_signature_invalid`, where every other structural refusal already lives.

Question 4 is genuinely distinct from check 2's `exp`. `exp` says when authority
*lapses*; `not_before` says when it *begins*, and no expiry can express "authorised,
but not until Monday". The instant compared is the Payment Mandate's own
`execution_date`, or now where it sets none — AP2's "when absent indicates immediate
execution".

## The accumulator

One row per Payment Mandate in `mandate_spend`, keyed by the mandate's `mandate_id`
(above). It holds
what AP2 calls the accumulated total, and the evaluation rule is the specification's
(`docs/ap2/payment_mandate.md:202-207`):

> the requested amount plus the total sum of amounts from previously closed Payment
> Mandates MUST be less than or equal to `max`. After approval, the amount MUST be
> added to the accumulated total for future evaluation.

**The mandate is never rewritten.** It is a signed credential and re-signing it would
need the principal's key, which lives in the wallet and never comes near the Desk. The
ceiling is read from the mandate; the running total against it is the Desk's own state.
This is what AP2 specifies too — the verifier tracks it.

### Evaluating is not spending

`SpendAuthorityCheck.evaluate` reads and writes nothing. `BudgetAccumulator.record_spend`
is what a **closed deal** calls.

That split has two consequences worth knowing:

- A deal the buyer walks away from costs the principal nothing. Nothing is reserved.
- `outcome.remaining` is a **forecast, not a reservation**. Two requests evaluated a
  moment apart are both told the same number.

So `record_spend` is the arbiter rather than the reporter: it takes the row's lock,
re-evaluates against the total as it stands at that instant, and raises `CeilingExceeded`
if the deal would breach the ceiling. Check 3 is the fast answer; this is the true one.

Underneath both, `spent <= ceiling` is a **database CHECK constraint**. If every line of
Python here were wrong, the ceiling a human signed would still hold, because the row
that breached it could not be written.

`record_spend` writes no audit entry. A spend is not an event in its own right — it is a
consequence of a deal closing, which is the negotiation ticket's event to record — so it
takes a caller's `conn` and the ledger row commits with the entry that explains it, or
neither does.

## Using it

```python
from desk.spend import BudgetAccumulator, Money, SpendAuthorityCheck, SpendRequest
from desk.spend import install_schema

with pool.connection() as conn:
    install_schema(conn)

accumulator = BudgetAccumulator(pool)

checkout = mandate_check.verify(checkout_mandate, presented_by=identity)
payment = mandate_check.verify_payment(payment_mandate, presented_by=identity)

outcome = SpendAuthorityCheck(accumulator, trail).evaluate(
    SpendRequest(item_id="SKU-COFFEE-1KG", amount=Money.of("750.00", "INR")),
    presented_by=identity,
    checkout=checkout,
    payment=payment,
)
outcome.passed        # bool
outcome.remaining     # Money on a pass — what closing would leave — None on a refusal
outcome.reason_code   # None on a pass
outcome.entry         # the audit entry this outcome wrote
```

`checkout` and `payment` are check 2's outputs, not claims. Passing an outcome that did
not verify raises rather than refusing: a refusal is an answer already, and running a
later check on it would invent a second one.

When the deal closes:

```python
with pool.connection() as conn:
    ledger = accumulator.record_spend(payment, amount=amount, conn=conn)
    trail.record(conn=conn, ...)      # the entry that explains the spend
ledger.remaining      # Money
```

## In the trail

Every outcome, pass or refusal, under `check_3_spend_authority_passed` /
`check_3_spend_authority_refused`, subject the agent. Amounts are strings, because a
`Decimal` is not JSON and rendering one as a float would put a number in the record
that differs from the number that was evaluated.

A pass:

```json
{"check": 3,
 "reasoning": "'SKU-COFFEE-1KG' is among the items the mandate authorises, and 750.00 INR fits inside the 2000.0 INR left of the 2000.0 INR its principal authorised",
 "evidence": {"requested_item": "SKU-COFFEE-1KG",
              "requested_amount": "750.00 INR",
              "mandate_id": "HwzNeGpCaAq4upoQeOmLaSVHdx7E61J6OHS_fs-_fgs",
              "ceiling": "2000.0 INR",
              "already_spent": "0 INR",
              "remaining": "2000.0 INR",
              "executes_at": "2026-08-29T12:05:38.847625+00:00",
              "not_before": null,
              "not_after": "2027-01-01T00:00:00+00:00",
              "would_leave": "1250.00 INR"},
 "state_change": {"request": "within spend authority"}}
```

"Exceeds the remaining balance" is an assertion until the ceiling, the accumulated total
and what is left are all in the entry beside it:

```json
{"check": 3,
 "reasoning": "2500.00 INR would take the total spent against this mandate to 2500.00 INR, past the 2000.0 INR its principal authorised",
 "evidence": {"requested_item": "SKU-COFFEE-1KG",
              "requested_amount": "2500.00 INR",
              "mandate_id": "HwzNeGpCaAq4upoQeOmLaSVHdx7E61J6OHS_fs-_fgs",
              "ceiling": "2000.0 INR",
              "already_spent": "0 INR",
              "remaining": "2000.0 INR"},
 "state_change": {"request": "refused"}}
```

And a `category_not_authorised` refusal records what *was* authorised beside what was
asked for, so nobody has to re-read the mandate to understand it:

```json
{"check": 3,
 "reasoning": "the mandate does not authorise 'SKU-LAPTOP-14'; authority for one thing is not authority for another",
 "evidence": {"requested_item": "SKU-LAPTOP-14",
              "requested_amount": "750.00 INR",
              "authorised_items": ["SKU-COFFEE-1KG"]},
 "state_change": {"request": "refused"}}
```

All three were produced by running the code, not written by hand.

## Interoperating

Both directions against Google's SDK at commit `e1ea56d`, for the Payment Mandate as
well as the Checkout Mandate (`tests/mandate/test_ap2_interop.py`). A ceiling expressed
with the SDK's own `Budget` model is one the Desk finds and draws down; a Payment
Mandate our wallet signs parses into the SDK's discriminated constraint models. See
[docs/mandates.md](mandates.md#interoperating) for how to build the throwaway
environment — the SDK is deliberately not a dependency.

Worth knowing: the SDK's generated model types `Budget.max` as a Python `float`. We read
the number off the wire rather than out of their object, so the exactness survives on
our side regardless.

---

## What this is not

- **Not a basket.** `SpendRequest` is one item. AP2's full `checkout.line_items`
  evaluation is a maximal-flow match over a whole checkout — quantities, and no
  requirement spent twice — and it belongs with the closed mandate the negotiation
  produces. Check 3 asks the narrower question the PRD asks: is this the *category*
  that was authorised.
- **Not freshness.** A request that passes here passes again if replayed. Check 4 owns
  the nonce and the window on the presentation hop.
- **Not the charge.** Nothing here moves money or talks to a payment rail.
- **Not the merchant.** `checkout.allowed_merchants` is read and carried but **not
  evaluated**, so a mandate scoped to a different merchant passes check 3 here.
  Evaluating it means the Desk knowing its own merchant identity, which the negotiation
  ticket introduces. Named here so the gap is open rather than silent.
- **Not the reputation ladder's ceiling.** The `payment.budget` ceiling is what the
  *principal* authorised. What a given agent is trusted with, by its rung, is a separate
  limit and a separate ticket (`ceiling_exceeded_for_tier`).
