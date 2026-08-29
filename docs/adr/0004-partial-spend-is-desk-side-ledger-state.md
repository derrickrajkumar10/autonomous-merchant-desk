# Partial spend is Desk-side ledger state, not a mutable mandate

FR-3.3 requires a remaining balance that decrements as a mandate is partially spent.
We keep that balance in Postgres keyed by mandate ID rather than in the mandate itself.

**Amended 2026-08-28.** This ADR originally claimed AP2 had no concept of partial spend and that
ours was an extension. Both are wrong. AP2 v0.2 specifies the **`payment.budget`** constraint,
whose normative evaluation rule is that the requested amount plus the sum of amounts from
previously closed Payment Mandates MUST be at or under `max`, with the amount added to the
accumulated total after approval. The decision below is unchanged and now better supported — AP2
reaches it too.

A mandate is a signed, immutable credential. Making it carry a running balance would
either invalidate the principal's signature or require re-signing on every deal — and
re-signing needs the principal's key, which FR-1.3 deliberately keeps out of the agent's
hands. A self-mutating mandate is therefore incompatible with our own key-separation rule.

## Consequences

The mandate asserts a ceiling; the Desk's ledger asserts what remains. Check 3 refuses on
`exceeds_remaining_balance` from ledger state, not from anything the counterparty presents.

**The ceiling is read from the mandate's `payment.budget` constraint**, not from a limit we hold
out-of-band. A buyer agent can therefore express its own budget without knowing anything about
StitchAI, which is what FR-11.1 requires; an out-of-band ceiling would work but would not
interoperate.

**Amended 2026-08-29, while building check 3.** *Which* mandate carries that constraint was left
unsaid above, and the omission was load-bearing. `payment.budget` is a constraint on the open
**Payment** Mandate. The open Checkout Mandate's schema admits only `checkout.line_items` and
`checkout.allowed_merchants` — `constraints.items.anyOf` in
`code/sdk/schemas/ap2/open_checkout_mandate.json` at commit `e1ea56d` — so a ceiling carried there
would not validate against the schema a stranger's library holds, and the interoperability this
ADR is written to protect would have been lost on the way to defending it.

So a buyer agent presents **two** open mandates, and AP2 pairs them itself: a `payment.reference`
constraint is mandatory on the Payment Mandate and carries the digest of the Checkout Mandate it
was signed for. The accumulator is keyed by the Payment Mandate's own digest, which is what the
spec's "total amount spent using this Payment Mandate" means.

The validity window lands in the same place and is worth naming, because it is *not* the mandate's
`exp`: `payment.execution_date`'s `not_before` and `not_after` can express "authorised, but not
until Monday", which an expiry cannot.

FR-11.3 should say we **implement** `payment.budget` — a stronger claim than extending the
standard, and one that comes with a spec-defined evaluation algorithm to cite.

Same epistemics as the rest of the Desk — it trusts its own books, never a counterparty's
claim about what is left.
