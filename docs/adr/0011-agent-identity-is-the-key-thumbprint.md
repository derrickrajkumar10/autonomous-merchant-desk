# An agent's identity is its key's thumbprint

Build step 2. Registration issues an agent identity, and that identity is the **RFC 7638 JWK
thumbprint** of the public key being registered, under an `agent-` prefix:

```
agent-OmPH0Gxw3cVs3ZxZDMViGNkb09zX-gI4eV2ebq9n3Uc
```

The alternative was a random handle allocated by the Desk and stored beside the key. Deriving
it instead buys three properties that are awkward to add later:

**One key is one identity, structurally.** A random handle admits the same key registering
twice and collecting two histories — which is trust farming with no attack required, since
reputation is per identity. Derivation makes that impossible rather than forbidden.

**Registration is idempotent.** A restarted agent re-registers and gets back the identity its
key already earned, with no "have I registered before?" state on the agent side and no second
arrival in the trail.

**The binding is checkable by a stranger.** Anyone holding the public key can recompute the
identity and see that they match, without asking the Desk. Nothing about the identity has to
be taken on our word, which is the same standard [ADR-0002](0002-jws-ed25519-for-all-signing.md)
sets for receipts.

## Implementation note: JWS is a library's job, not ours

Signing and verification are PyJWT's, not code of our own. Interoperability is the whole
reason [ADR-0002](0002-jws-ed25519-for-all-signing.md) chose JWS, and a hand-rolled
implementation of a standard is the fastest way to be subtly incompatible with it — quite
apart from being the wrong thing to hand-roll. Our code owns the format (which algorithm,
which `typ`, where the identity is claimed) and the refusal reasons; the cryptography is the
library's.

## Consequences

Key rotation does not preserve identity: a new key is a new agent with no history, which is
the right default for a system where history *is* the reputation. If rotation is ever needed,
it has to be an explicit, recorded succession from one identity to another — not a quiet
update of a key column, which derivation makes impossible anyway.

An identity is knowable from the public key alone, so possessing one proves nothing. It is
registration that makes an identity real, and the signature on each request that makes
claiming one worth anything.
