# The Desk signs the closed Checkout Mandate

Build step 6. A negotiation that reaches agreement produces a **closed Checkout Mandate**
(`mandate.checkout.1`) capturing the terms, and in this system **the Desk signs it** — both
the inner merchant-signed Checkout payload and the outer envelope around it.

Half of that is AP2's own design and half of it is a deliberate divergence, and they are worth
separating.

## The half that is AP2's

`code/sdk/schemas/ap2/checkout_mandate.json` gives the closed mandate a `checkout_jwt` field,
described as "base64url-encoded serialized **merchant-signed** JWT of the Checkout payload",
and a `checkout_hash` naming it. The merchant signs the terms because the merchant is the party
stating them. That is exactly what FR-5.6 asks for when it says the Checkout JWT is signed
ES256, and it is why the Desk needs a keypair of its own at all.

AP2 puts the *contents* of that payload deliberately out of scope
(`docs/ap2/checkout_mandate.md:30-33`). So the negotiated unit prices, the charges, the terms
and the digest of the open mandate the deal was struck under all live inside the standard
rather than beside it, and nothing about FR-5.6 required inventing a field.

## The half that is ours

`docs/ap2/specification.md:178-190` says that in the autonomous case the **agent** signs the
outer closed mandate, with the key the open mandate bound in its `cnf` claim. Here the Desk
signs that too.

The reason is that a negotiation is a conversation and not a form. The Desk has to be able to
say what it agreed to at the moment it agreed, whether or not the counterparty comes back to
counter-sign — and the counterparty's acceptance is already recorded, in an entry the Desk
cannot alter afterwards. Waiting for a signature that may never arrive would leave the Desk's
own commitment unrecorded, which is the opposite of what this artefact is for.

## What it costs

**A closed mandate here proves what the Desk committed to. It does not prove the buyer
agreed.** That is a genuinely weaker claim than a conformant AP2 chain makes, and nothing in
the code or the prose may describe it as more. The evidence that the buyer agreed is the
audit trail, which is hash-chained and append-only — good evidence, and evidence of a
different kind, because it is the Desk's own record rather than a signature the buyer made.

It also means a stranger verifying one of these learns the merchant's side only. Ticket 30
publishes the protocol and ships a reference client, and adding the agent's counter-signature
over the envelope is that ticket's to do. The shape is ready for it: the inner document is
untouched by a second signature over the outer one, so a counter-signed mandate carries the
same `checkout_hash` and the same terms.

## Consequences

The Desk holds a private key, which every other part of this design has been careful to avoid.
That is not a contradiction of CONTEXT.md §7's rule, and the distinction is worth stating: the
wallet exists because the *principal's* key confers authority, so an agent holding it could
authorise purchases for a human. The Desk's key confers nothing. It signs statements the Desk
is making about itself, which the Desk is the only party entitled to make and is making
anyway. A stolen Desk key forges the Desk's commitments — an ordinary server-key problem, not
the delegation hole the wallet closes.

The key is generated per process for now. A receipt "verifiable by a third party given the
Desk's public key" (FR-7.3) needs one that outlives a restart, and persisting it is ticket 09's
along with the receipts that need it.
