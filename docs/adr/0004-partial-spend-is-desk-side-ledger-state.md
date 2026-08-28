# Partial spend is Desk-side ledger state, not a mutable mandate

FR-3.3 requires a remaining balance that decrements as a mandate is partially spent.
We keep that balance in Postgres keyed by mandate ID rather than extending AP2's mandate
to carry it.

A mandate is a signed, immutable credential. Making it carry a running balance would
either invalidate the principal's signature or require re-signing on every deal — and
re-signing needs the principal's key, which FR-1.3 deliberately keeps out of the agent's
hands. A self-mutating mandate is therefore incompatible with our own key-separation rule.

## Consequences

The mandate asserts a ceiling; the Desk's ledger asserts what remains. Check 3 refuses on
`exceeds_remaining_balance` from ledger state, not from anything the counterparty presents.
This is a real extension of AP2 and must be documented as such under FR-11.3: *partial-spend
accounting is merchant-side ledger state keyed by mandate ID; the mandate itself stays
immutable and single-signed.*

Same epistemics as the rest of the Desk — it trusts its own books, never a counterparty's
claim about what is left.
