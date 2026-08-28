# JSON Web Signatures over Ed25519 for all signing

Every signature in the system — principal-signed mandates, agent request signatures, and
Desk-issued receipts — uses JWS with Ed25519. Chosen over a bespoke signing scheme because
it is a standard wrapper with library support in every language, which is what makes
FR-11.1 (a judge writes their own buyer agent and it transacts) realistic rather than a
claim.

## Known exception: the Checkout JWT is ES256

**Amended 2026-08-28.** "Ed25519 for all signing" as originally written is incompatible with the
specification we adopt. AP2 v0.2 requires the Checkout JWT be signed with a *non-deterministic*
scheme, because `checkout_hash` relies on entropy contributed by the signature itself to prevent
brute-forcing checkout contents. Ed25519 is deterministic and contributes none.

The spec permits Ed25519 if the checkout payload carries an explicit salt — but Google's own SDK is
ES256-only (`alg: Literal['ES256']`), so a third party verifying our checkout with the official
library would fail on EdDSA regardless of salt. Since interoperability is this ADR's entire reason
for existing, the exception follows from the rule rather than contradicting it.

- **Checkout JWT: ES256** (ECDSA P-256 / SHA-256).
- **Everything else: Ed25519** — agent request signatures and Desk-issued receipts, neither of
  which AP2 constrains.

See [the AP2 research note](../research/ap2-mandate-model.md) for the citations.

## Consequences

Third parties can verify Desk receipts with off-the-shelf JOSE libraries given the Desk's
public key. Key distribution and rotation are ours to define; JWS does not solve them.

Two algorithms means two key types. Keep the distinction explicit in code and in the audit trail;
a signing path that silently picks the wrong one is the kind of failure that verifies fine locally
and fails against a stranger's verifier.
