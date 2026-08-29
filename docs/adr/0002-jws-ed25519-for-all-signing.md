# JSON Web Signatures over Ed25519 for all signing

Every signature in the system — principal-signed mandates, agent request signatures, and
Desk-issued receipts — uses JWS with Ed25519. Chosen over a bespoke signing scheme because
it is a standard wrapper with library support in every language, which is what makes
FR-11.1 (a judge writes their own buyer agent and it transacts) realistic rather than a
claim.

## Known exception: everything AP2 reads is ES256

**Amended 2026-08-28, and widened 2026-08-29 (ticket 03).** "Ed25519 for all signing" as
originally written is incompatible with the specification we adopt. The exception now covers
**every artefact AP2's own tooling has to read**, which is the Checkout JWT and the
principal-signed mandates, for two separate reasons.

### The Checkout JWT: the specification forbids Ed25519

AP2 v0.2 requires the Checkout JWT be signed with a *non-deterministic* scheme, because
`checkout_hash` relies on entropy contributed by the signature itself to prevent
brute-forcing checkout contents. Ed25519 is deterministic and contributes none. The spec
permits Ed25519 if the checkout payload carries an explicit salt — but Google's SDK is
ES256-only, so a third party verifying our checkout with the official library would fail on
EdDSA regardless of salt.

### Mandates: the SDK cannot sign or verify Ed25519 at all

The specification does not forbid Ed25519 for mandates. Google's implementation of it simply
cannot produce or consume one, and an unimplementable conformance claim is worth nothing. Two
independent walls, both confirmed by running the SDK at commit `e1ea56d`:

- **Signing.** `ap2.sdk.sdjwt.common.issue_sd_jwt` passes `sign_alg=None` to `sd-jwt` 0.10.4,
  which defaults to ES256 and hands the key to jwcrypto's EC signer. Given an Ed25519 key that
  raises `AttributeError: 'ed25519' object has no attribute 'key_size'` — before reaching any
  signature. There is no parameter that changes this.
- **Key binding.** `ap2.sdk.generated.types.jwk.JsonWebKey` is `kty: Literal['EC']`,
  `crv: Literal['P-256']`, `alg: Literal['ES256']`, with `extra='forbid'`. An `OKP` / `Ed25519`
  JWK does not validate against it.

So the principal's key is **ECDSA P-256** and mandates are signed **ES256**. The agent's key
stays Ed25519, and this is the arrangement `tests/mandate/test_ap2_interop.py` exercises in
both directions against the real SDK.

### Where this lands

- **Mandates and the Checkout JWT: ES256** (ECDSA P-256 / SHA-256).
- **Everything else: Ed25519** — agent request signatures and Desk-issued receipts, neither of
  which AP2 constrains.

### The cost, stated plainly

Two schemes instead of one, and a `cnf` claim that is interoperable only up to a point. The
Desk binds mandates to the agent's **Ed25519** key, which the SDK carries and returns intact on
a root mandate — proven by the interop tests — but which its `JsonWebKey` model would reject if
a delegation hop were built on top of it. A closed mandate produced by the SDK's own chain
machinery would therefore need an EC agent key.

That trade was made deliberately. ADR-0011 makes an agent's identity its key's thumbprint, so
giving agents a second key for mandate presentation would mean an agent with two identities,
which is the confusion the whole identity subsystem exists to prevent. Interoperability that
costs the identity model is not worth having.

**Ticket 05 met that boundary and did not move it.** The key-binding JWT check 4 reads proves
possession of whichever key the mandate's `cnf` endorses, so ours is signed **EdDSA** while AP2's
OpenID4VP request advertises `"kb-jwt_alg_values": ["ES256"]`. That is this same exception seen
from the other side rather than a third one: the issuer signs ES256 so a stranger's library can
read the mandate, and the holder signs Ed25519 because that is the key the holder has. What it
costs is that the SDK's own `kb_sd_jwt` helper cannot build our hop — but nor could a verifier
restricted to ES256 have consumed our `cnf`, so the interoperability was already spent.

See [the AP2 research note](../research/ap2-mandate-model.md) for the field-level citations.

## Consequences

Third parties can verify Desk receipts with off-the-shelf JOSE libraries given the Desk's
public key. Key distribution and rotation are ours to define; JWS does not solve them.

Two algorithms means two key types. Keep the distinction explicit in code and in the audit
trail; a signing path that silently picks the wrong one is the kind of failure that verifies
fine locally and fails against a stranger's verifier. Since ticket 03 the two roles are
different classes over different schemes — `AgentPublicKey` holds thirty-two raw Ed25519
bytes, `PrincipalPublicKey` a sixty-five byte uncompressed P-256 point — so neither can be
reinterpreted as the other even deliberately, and the database CHECK constraints say the same
thing a second time.
