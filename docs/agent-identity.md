# Agent identity and check 1

Before the Desk can decide whether a request is authorised, it has to know who is
asking. This document is the contract an external buyer agent codes against: how to
register, how to sign, and what the Desk does with the result.

It is the first half of one sentence that has to stay true everywhere:

> **The principal's key authorises spending; the agent's key only proves who is asking.**

Decisions behind it: [ADR-0002](adr/0002-jws-ed25519-for-all-signing.md) for the
signing scheme, [ADR-0011](adr/0011-agent-identity-is-the-key-thumbprint.md) for where
an identity comes from.

---

## Registering

A buyer agent generates its own Ed25519 keypair, keeps the private half, and registers
the public half together with the principal it acts for (FR-2.1).

```python
from world.agents.keys import AgentKeypair

keypair = AgentKeypair.generate()
identity = registry.register(public_key=keypair.public_key, principal_id="principal-asha")
identity.agent_id        # 'agent-OmPH0Gxw3cVs3ZxZDMViGNkb09zX-gI4eV2ebq9n3Uc'
```

The identity is the key's RFC 7638 thumbprint, so one key is one identity for ever and
a returning agent re-registers into the identity it already has.

Registering an already-registered key under a *different* principal is refused, and the
attempt is written to the trail as `agent_registration_refused` /
`agent_principal_mismatch`. A public key is public, so this is something a stranger can
try: it is an attempt to move an identity's stated source of authority, which is worth
seeing rather than merely raising. An identity does not change principal; a new key is
a new identity.

The registry holds five columns — the identity, the public key, its algorithm, the
principal, and when it arrived. No private key material, ever; the Desk holds its own
key and nobody else's.

### Registration buys an identity, not trust

A newly registered agent sits at the bottom rung under the strictest scrutiny
(FR-2.3). Nothing on `AgentIdentity` is a ceiling, a score or a balance, because
anything that looked like one there would make identity read as authority. What
registration buys is accountability: from here on, behaviour attaches to a key.

The arrival is written to the trail as `agent_registered`, and the row and its entry
commit together — a registered agent the trail never saw arrive would be the trail
disagreeing with reality.

---

## The signed request

Every subsequent request is a JWS in compact serialisation, signed Ed25519 and
verified against the registered public key (FR-2.2).

```python
request = keypair.sign_request({"sku": "COFFEE-1KG", "quantity": 2}, agent_id=identity.agent_id)
```

| Part | Holds |
|:---|:---|
| `alg` | `EdDSA`. Always, for agent requests. |
| `kid` | The agent identity being claimed. |
| `typ` | `stitchai-request+jws`. |
| payload | The request body, as JSON. |

Three things about the shape are deliberate:

**The body is inside the signature.** There is no envelope around it and nothing beside
it, so there is no part of a request a signature does not cover. Altering a body in
flight is not a difference the Desk has to notice — it is a signature that no longer
verifies.

**The identity is claimed in `kid`, not proven by it.** A header is not evidence. The
`kid` says which registered key to check the signature against, and the signature is
the only thing that decides anything.

**`typ` is inside the protected header.** A signature over a receipt is not a signature
over a request, however valid it is, so what the signature is *over* is signed too.

### `EdDSA`, and the one exception

Agent requests are Ed25519 and a request naming any other algorithm is refused. The
ES256 exception in [ADR-0002](adr/0002-jws-ed25519-for-all-signing.md) applies to the
AP2 Checkout JWT alone — do not over-apply it. The algorithm a request named is written
to the trail on every outcome, pass or refusal, so a wrong-algorithm path is visible
rather than silent.

---

## Check 1

```python
outcome = IdentityCheck(registry, trail).verify(request)
if outcome.passed:
    outcome.identity                 # the registered agent
    outcome.body                     # what the signature covered
```

The body is only available after the check, because before it there is nothing but
unverified bytes.

A pass says exactly one thing: **this request came from this registered agent and
reached the Desk unaltered.** It says nothing about whether a human authorised the
spend, whether the request is fresh, or whether the text inside it is safe. Those are
checks 2 through 5, and a pass here must never be read as standing in for them. The
entry records `state_change: {"request": "identified"}` — identified, not authorised.

Cryptography decides this check. No model may (FR-3.1).

### Refusals

Every check-1 refusal leaves under one reason code, `agent_signature_invalid`:

| What happened | What the requester learns |
|:---|:---|
| The key is not registered | `agent_signature_invalid` |
| The signature does not verify | `agent_signature_invalid` |
| The body was altered after signing | `agent_signature_invalid` |
| It was signed by another registered agent | `agent_signature_invalid` |
| It names an algorithm other than `EdDSA` | `agent_signature_invalid` |
| It is not a readable JWS | `agent_signature_invalid` |

From outside they are one answer — *that signature does not belong to a registered
agent* — because telling a prober which half of its lie was believed is telling it
where to push next. Inside, they are told apart in the trail, which is a reader we
trust:

```json
{
  "check": 1,
  "reasoning": "no agent is registered under the key this request claims to be signed by",
  "evidence": { "claimed_agent_id": "agent-...", "algorithm": "EdDSA" },
  "state_change": { "request": "refused" }
}
```

A stated reason proves a check exists; a generic refusal proves nothing (CONTEXT.md
section 5, principle 3). A refusal is recorded against the identity the request
claimed, so an agent's detail panel shows the requests that failed in its name as well
as the ones that succeeded.

---

## What this is not

- **Not authorisation.** Check 2 verifies the principal's mandate, check 3 the spend
  against it.
- **Not freshness.** A signed request replayed a second time verifies here exactly as
  it did the first. Check 4 owns that.
- **Not a session.** Requests are individually signed; there is nothing to log into and
  nothing to steal but the key itself.
- **Not key rotation or revocation.** Real concerns, deliberately not this build.
