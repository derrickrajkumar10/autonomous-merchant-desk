# Ticket 03 — Mandates, and check 2

> Ticket 02 taught the Desk to recognise who is knocking. This one teaches it to ask
> whether a human said yes.

---

## 1. The situation

You tell your phone: *"restock my coffee, keep it under 2,000 rupees."* You put the
phone down. Some minutes later something buys coffee.

Now stand on the other side of that. You run the shop. A program you have never met
sends you a message saying a person authorised it to spend up to 2,000 rupees on
coffee. You have no session, no cookie, no card form, no human to phone. What would
you need to see before you sold it anything?

Two things, and they are different questions:

1. **Is this program who it says it is?** That was the last ticket. It has a key, you
   have its key, the message is signed, the signature checks out.
2. **Did a person actually authorise this?** That is this ticket. And notice that the
   first answer does not help you at all with the second. A program can be perfectly,
   provably itself and still be waving around authority it was never given.

The gap between those two sentences is the entire reason this ticket exists.

## 2. The obvious solution, and why it fails

The obvious answer: have the human sign something. The human's phone holds a secret;
it uses that secret to produce a *signature* over the words "up to 2,000 rupees on
coffee"; the shop checks the signature; done.

That works, and it is what we do. But it has a hole, and the hole is the interesting
part.

**A signed authorisation is a bearer instrument.** Like cash, or a cinema ticket —
whoever is holding it can use it. If the coffee-buying program leaks that signed
document, or a bug in it leaks the document, or someone breaks into the machine it
runs on, then *whoever now has it* can walk up to the shop, present it, and buy 2,000
rupees of coffee. The signature is still perfectly valid. The human really did sign
it. It just isn't the human's program presenting it any more.

So a signed authorisation alone is not enough. It needs to be un-stealable.

## 3. Making it un-stealable

Here is the trick, and it is a genuinely nice one.

When the human signs the authorisation, they include *inside it* the public key of the
one program allowed to present it. Not its name — its key. So the document reads,
roughly:

> Up to 2,000 rupees on coffee, until 4pm, and only for whoever can prove they hold
> the private half of **this** key.

Now stealing the document buys you nothing. You can show it to the shop, and the shop
will read it, and the shop will then check whether the message it arrived in was
signed by the key named inside the document. It wasn't — because you don't have that
private key, only the original program does. Refused.

This turns the document from cash into something more like a boarding pass with a name
on it. Finding one on the floor doesn't get you on the plane.

The name for this is **key binding**. The field it lives in is called `cnf`, short for
"confirmation" — the shop is confirming, before it acts, that the presenter can prove
possession of the key the human named.

**And we did not invent it.** This is worth being blunt about, because the temptation
to claim it is strong. AP2 — Google's Agent Payments Protocol, the specification we
follow — makes key binding a **MUST** on exactly this kind of authorisation. Our
contribution is elsewhere: AP2 binds an authorisation to *a* key, and says nothing at
all about who owns that key, whether it is registered, or what it has done before.
That is our registry and our reputation ladder. Claiming AP2's own requirement as our
innovation is precisely the sort of thing that falls apart under questioning.

## 4. The vocabulary, now that you need it

Three words, each introduced only now that the idea behind it is already clear.

- A **mandate** is the signed authorisation. Not a permission, not a token — a
  mandate. One human, one signature, a set of constraints, an expiry.
- A **principal** is the human whose signature is on it. Their money, their authority.
- **Check 2** is the Desk's name for the moment it decides whether to believe one.

And one more distinction that runs through everything below, because getting it wrong
is the mistake this whole area is built to prevent:

> **The principal's key authorises spending. The agent's key only proves who is
> asking.**

Two keys, two jobs, and they are never the same key.

## 5. What check 2 actually does

Three questions, in this order:

| # | Question | Refused as |
|:--|:---|:---|
| 1 | Does the principal's signature verify? | `mandate_signature_invalid` |
| 2 | Has the mandate expired? | `mandate_expired` |
| 3 | Does it name **this** agent's key? | `agent_mandate_mismatch` |

The order matters and is not a style choice. Nothing a mandate says means anything
before its signature verifies. Reading an expiry date out of an unverified mandate is
reading whatever the sender felt like writing.

Every one of those three outcomes — and the pass — is written to the audit trail, with
the reasoning, the evidence, and what changed. A refusal that states its reason proves
a check exists. A generic one proves nothing.

### The question that isn't there

Notice what check 2 does *not* ask: **is 2,000 rupees enough for what they want to
buy?** That is check 3, and it is a separate ticket. Check 2 establishes that a human
authorised *something* and that this agent is the one allowed to ask. Whether the
specific thing being asked for falls inside that authorisation is a different question
with a different refusal reason.

## 6. Where the key comes from — the part that is easy to get wrong

Question 1 above says "does the principal's signature verify?". Verify *against what*?

The tempting answer is: the mandate says which principal signed it, so look up that
principal's key. This is wrong, and wrong in a way that would quietly undo the whole
check. A forger writes the mandate. A forger therefore chooses which principal it
claims to be from. They would simply name themselves.

So the Desk never reads the mandate's own account of who signed it. The chain is:

```
this request  →  (check 1)  →  this agent
this agent    →  registered under  →  this principal
this principal →  the Desk's own record  →  this public key
```

Every link is something the Desk established for itself. The mandate contributes
nothing to choosing the key it will be checked against.

That last link is a small new table, the **principal directory**: which humans the Desk
honours mandates from, and under which key. It is configuration — *whose authorisations
do we accept* — rather than a record of anything a counterparty did, which is why
enrolling a principal writes no audit-trail entry while registering an agent does.

The mandate's *claim* about who signed it is still recorded, as evidence, right beside the
principal actually used:

```json
{"claimed_principal_id": "principal-someone-else", "verified_against": "principal-asha"}
```

Those two lines sitting side by side are what turns an attempt from *refused now* into
*findable later*.

## 7. The format, and one genuinely surprising thing about it

A mandate is not a plain signed blob. AP2 secures it as an **SD-JWT** — "selective
disclosure JWT", RFC 9901 — and the shape is:

```
<signed part>~<disclosure>~<disclosure>~
```

The signed part does not contain the mandate's contents. It contains *hashes* of them.
The actual contents travel alongside, as **disclosures**, one per withheld part.

The surprising consequence: **the holder is allowed to delete disclosures**, and the
signature still verifies. That is the whole point of the format. A mandate might
authorise five things, and the agent presenting it can choose to show you only the one
that concerns you, and you can still verify the human signed it.

That is genuinely useful — for a verifier who needs one fact. It is wrong for this one,
and working out why is the most interesting thing in this ticket.

### Why the Desk refuses a mandate it can only partly see

Picture a mandate with two constraints: *coffee, two kilos* and *only from this
merchant*. Now the agent presenting it deletes the second disclosure.

Nothing has been forged. The signed part is untouched, the signature verifies, and what
arrives is still recognisably a mandate — it still has line items, it still names the
agent. It has simply stopped saying where the coffee may be bought.

And the next check along, check 3, evaluates the constraints it is given. Given fewer,
it permits more. **The holder has widened its own authorisation by sending less.**

So the Desk requires a mandate to be fully disclosed. A constraint it cannot see is a
constraint it cannot honour, and refusing is the only safe reading. That is a deliberate
narrowing of RFC 9901, not an implementation of it, and it is written down as such in
the code.

**What it costs.** The format lets an issuer scatter *decoy* digests — placeholders that
resolve to nothing, so a verifier cannot tell how many parts were withheld. Demanding
everything refuses those too. AP2's SDK does not emit them, and they buy nothing against
a verifier that demands the whole mandate anyway, so the price is low — but it is a
price, and an issuer who used them would find their mandates refused.

### The other direction

**Adding** a disclosure is refused too, and this one is subtle, because adding one does
not break the signature either — the signed part is untouched. If the verifier merely
ignored material no hash asked for, an attacker could staple content onto a mandate they
had not altered and have it verify.

Four refusals in total, then: a part withheld, a part added, one disclosure made to
stand for two claims, and a disclosure that would overwrite something the principal sent
in the clear.

There is one more small trap. The hash is taken over the disclosure's *encoded
characters exactly as they arrived* — not over the value inside. A verifier that
decoded a disclosure and re-encoded it before hashing would get a different answer for
a byte-identical mandate. So the received string is what travels through the hashing,
untouched.

## 8. The decision that cost the most

Everything in the system signs with **Ed25519**. It is fast, small, and there is a
library for it in every language. ADR-0002 said: Ed25519 for all signing.

Mandates cannot use it.

Not because AP2 forbids it — AP2 doesn't. Because Google's own AP2 SDK **cannot sign or
verify an Ed25519 mandate at all**, and a conformance claim nobody can check is worth
nothing. Two independent walls, both found by running the SDK rather than reading about
it:

- Its SD-JWT layer passes no algorithm down to the library underneath, which defaults
  to ES256 and hands the key to its ECDSA routine. An Ed25519 key gets as far as
  `AttributeError: 'ed25519' object has no attribute 'key_size'` — before any signature
  is attempted. No parameter changes this.
- Its JWK model is `kty: Literal['EC']`, `crv: Literal['P-256']`, with extra fields
  forbidden. An Ed25519 key does not validate against it.

So the principal's key is **ECDSA P-256** and mandates are signed **ES256**. The agent's
key stays Ed25519.

**What that cost.** Two signature schemes in the system where there was one, and a
key-binding claim that is interoperable only up to a point: the Desk binds mandates to
the agent's *Ed25519* key, which the SDK carries and hands back intact on a mandate like
ours — the tests prove it — but which its JWK model would reject if someone tried to
build a delegation chain on top.

We took that deliberately. An agent's identity **is** its key's fingerprint (ADR-0011),
so giving agents a second key for mandate presentation would mean an agent with two
identities — exactly the confusion the identity subsystem exists to prevent.
Interoperability bought at the price of the identity model is not worth having. Ticket
05 will meet that boundary when it builds the key-binding hop, and it is written down
now rather than discovered then.

There is an upside worth naming. The two roles are now different *schemes*, not just
different class names. A principal's key physically cannot verify an agent request and
an agent's key physically cannot verify a mandate — the separation stopped being a
convention and became a property.

## 9. Proving it, rather than asserting it

The claim "we implement AP2" is cheap. A specification you implement alone is a
specification you have interpreted alone, and interpretation is where conformance
quietly dies.

So the test suite runs both directions against Google's actual SDK:

- A mandate **the official SDK produced** verifies in our path — including resolving
  the disclosures the SDK chose to make, which are not the ones ours makes.
- A mandate **our wallet produced** verifies in the SDK's, parses into its own
  `OpenCheckoutMandate` model, and the agent key comes back out of `cnf` unchanged.
- And the negative half: the SDK **refuses** a mandate whose disclosure we tampered
  with. Without this one, interoperating on what verifies would prove much less — a
  verifier that accepted everything would also have passed.

The SDK is pinned to commit `e1ea56d` and installed from Google's repository, not from
PyPI. The package named `ap2` on PyPI is a third party's mirror of the superseded v0.1
model under a different licence; `pip install ap2` does not get you Google's code.

Its dependency pins are all exact — `cryptography==46.0.5`, `pytest==9.0.2`,
`pydantic==2.12.5` — so it is deliberately **not** a dependency or an extra of this
project. Declaring it in any form that takes part in resolution drags everything else
down to those versions: an ordinary `uv sync` would silently downgrade cryptography to
run a conformance test nobody asked for. It goes into a throwaway environment instead,
and `pyproject.toml` carries the commands.

Without it, those three tests **skip and say so** rather than passing quietly:

```
SKIPPED [1] the official AP2 SDK is not installed, so AP2 conformance was not
exercised. It is not a dependency of this project on purpose -- see the throwaway-
environment commands in pyproject.toml, above [build-system].
```

### Counts actually seen

Run on 2026-08-29 against Python 3.11.9 and an embedded Postgres:

| Environment | Result |
|:---|:---|
| Project venv, no SDK | **126 passed, 1 skipped** |
| Throwaway venv with the SDK | **129 passed** |

(One skip rather than three: the whole module is skipped at import, before its three
tests are collected.)

`ruff check`, `ruff format --check` and `mypy --strict` are clean across all 43 files.

## 10. What this ticket deliberately does not do

| Left out | Who owns it |
|:---|:---|
| Reading the `payment.budget` ceiling and drawing it down across deals | Ticket 04 (check 3) |
| Nonce and freshness — the replay window, and the `nonce`/`aud` on the presentation hop | Ticket 05 (check 4) |
| A wallet as a **separate process** that signs nothing without a human saying yes | Ticket 25 |
| Voice capture, and the prompt playback the wallet would show the human | Ticket 26 |
| The **closed** Checkout Mandate — the specific negotiated deal | Ticket 08 onward |

Two of those deserve a sentence each.

**The wallet here is a keypair, not a product.** `world/wallet/` holds the principal's
key and can sign a mandate, which is the least that lets check 2 be tested against a
real signature rather than a fixture. The rule it already keeps is the one that matters:
nothing in `desk/` and nothing in `world/agents/` imports it, so the principal's private
key is nowhere the buyer agent could reach. Ticket 25 makes it a genuine separate
process with a human in the loop.

**A mandate with no expiry is accepted.** AP2 makes `exp` optional — only RECOMMENDED —
so refusing one for its absence would refuse a conformant mandate. What bounds such a
mandate instead is the freshness window on the *presentation*, which is check 4's job.
That was a real gap when this ticket shipped, and it was better said than left for
someone to find; [ticket 05](ticket-05-replay-and-freshness.md) closed it.

## 11. The code

| File | What it is |
|:---|:---|
| [desk/mandate/sdjwt.py](../../desk/mandate/sdjwt.py) | RFC 9901: signature, disclosures, the three refusals in §7 |
| [desk/mandate/checkout.py](../../desk/mandate/checkout.py) | AP2 v0.2: `vct`, constraints, `cnf`, expiry |
| [desk/mandate/check.py](../../desk/mandate/check.py) | check 2 itself — the only part that writes to the trail |
| [desk/identity/principals.py](../../desk/identity/principals.py) | the principal directory of §6 |
| [desk/identity/keys.py](../../desk/identity/keys.py) | `AgentPublicKey` (Ed25519) and `PrincipalPublicKey` (P-256) |
| [world/wallet/keys.py](../../world/wallet/keys.py) | the **principal's** side: holding the key and signing a mandate |

The two Desk-side layers are kept apart on purpose. `sdjwt.py` knows about signatures
and knows nothing about commerce; `checkout.py` knows about mandates and knows nothing
about cryptography. `check.py` sits on both.

### Using it

```python
from desk.audit import AuditTrail
from desk.identity import AgentRegistry, PrincipalDirectory
from desk.mandate import MandateCheck

# Once: the Desk records whose authorisations it honours.
PrincipalDirectory(pool).enrol(principal_id="principal-asha", public_key=wallet.public_key)

# The principal's wallet signs, naming the one agent allowed to present it.
mandate = wallet.sign_open_checkout_mandate(
    principal_id="principal-asha",
    agent_key=agent.public_key,
    constraints=[{"type": "checkout.line_items", "items": [...]}],
    expires_at=int(time.time()) + 3600,
)

# The Desk, after check 1 has produced `identity`.
outcome = MandateCheck(PrincipalDirectory(pool), trail).verify(mandate, presented_by=identity)
if outcome.passed:
    ...                            # outcome.mandate carries the constraints
else:
    ...                            # outcome.reason_code names which of the three refused it
```

`presented_by` is check 1's output, not a claim. Handing it an identity the Desk has not
just authenticated would make this check verify a binding to a *name* rather than to a
*key*, which is the one thing it exists not to do.

## 12. Glossary

| Term | Means |
|:---|:---|
| **Mandate** | A signed authorisation from a human. Never a "permission" or a "token". |
| **Principal** | The human whose signature is on it. Their money, their authority. |
| **Open mandate** | The forward-looking kind: constraints, for a purchase not yet agreed. |
| **Closed mandate** | The other kind: one specific negotiated deal. Not this ticket. |
| **Key binding** / **`cnf`** | The claim naming the one agent's key allowed to present it. |
| **SD-JWT** | The format. Signed hashes, with the contents alongside as disclosures. |
| **Disclosure** | One withheld part. Dropping one is allowed; adding one is refused. |
| **`vct`** | Which of AP2's four mandate shapes this is. Ours: `mandate.checkout.open.1`. |
| **AP2** | Google's Agent Payments Protocol. We follow v0.2; v0.1 had different mandates. |
| **ES256** | ECDSA over P-256. What mandates are signed with, and only mandates (§8). |
| **Principal directory** | The Desk's record of which humans it honours mandates from. |

---

## 13. Next

**Ticket 04 — check 3, spend authority.** A human authorised *something*. The next
question is whether what is being asked for now is inside it: the amount against the
`payment.budget` ceiling, the category, the validity window. And the ceiling is drawn
down across deals without the mandate ever being rewritten — the mandate stays
immutable and the running total is the Desk's own state.

*Written after the fact:* that paragraph says "the mandate", and ticket 04 found the
word was doing too much work. `payment.budget` is an open **Payment** Mandate
constraint, and this ticket built only the open Checkout Mandate — so an errand turns
out to be two mandates, paired by digest. See
[the ticket 04 explainer](ticket-04-spend-authority.md) §4.

Which is the same shape as before: check 3 is only meaningful because check 2 exists.
There is no point measuring a spend against an authorisation until you know the
authorisation is real.
