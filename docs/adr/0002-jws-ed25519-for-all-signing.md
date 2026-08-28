# JSON Web Signatures over Ed25519 for all signing

Every signature in the system — principal-signed mandates, agent request signatures, and
Desk-issued receipts — uses JWS with Ed25519. Chosen over a bespoke signing scheme because
it is a standard wrapper with library support in every language, which is what makes
FR-11.1 (a judge writes their own buyer agent and it transacts) realistic rather than a
claim.

## Consequences

Third parties can verify Desk receipts with off-the-shelf JOSE libraries given the Desk's
public key. Key distribution and rotation are ours to define; JWS does not solve them.
