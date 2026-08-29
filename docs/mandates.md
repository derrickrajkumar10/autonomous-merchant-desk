# Mandates and check 2

Check 1 established *who is asking*. This is the second half of the sentence:

> **The principal's key authorises spending; the agent's key only proves who is asking.**

This document is the contract an external buyer agent and an external wallet code
against: what a mandate is, what the Desk checks about one, and what it refuses.

The shape is not ours. It is **AP2 v0.2**'s, secured as an SD-JWT
([RFC 9901](https://www.rfc-editor.org/rfc/rfc9901.html)), carrying the presenting agent's
public key in a `cnf` claim (RFC 7800). Field-level citations are in
[the research note](research/ap2-mandate-model.md) §1a; the reasoning a newcomer wants is
in [the explainer](explainers/ticket-03-mandate-library.md).

**One errand is two mandates.** AP2 v0.2 splits them: the open Checkout Mandate
(`mandate.checkout.open.1`) below says *what may be bought*, and an open Payment Mandate
(`mandate.payment.open.1`) says *what may be spent* — the ceiling, the currency and the
execution window. This document covers the first and the three questions check 2 asks of
either; the second, and everything check 3 does with it, is in
[docs/spend-authority.md](spend-authority.md).

Decisions behind it: [ADR-0002](adr/0002-jws-ed25519-for-all-signing.md) for why a
mandate is ES256 while everything else is Ed25519.

---

## What a mandate carries

```json
{
  "vct": "mandate.checkout.open.1",
  "constraints": [
    {"type": "checkout.line_items",
     "items": [{"id": "beans",
                "acceptable_items": [{"id": "SKU-COFFEE-1KG", "title": "Beans, 1kg"}],
                "quantity": 2}]}
  ],
  "cnf": {"jwk": {"crv": "Ed25519", "kty": "OKP", "x": "..."}},
  "iat": 1787997844,
  "exp": 1788001444
}
```

| Field | Required | What it is |
|:---|:---|:---|
| `vct` | yes | Which mandate shape. Only `mandate.checkout.open.1` is read here. |
| `constraints` | yes | What the principal authorised. At least one `checkout.line_items`. |
| `cnf` | yes | The **one agent** allowed to present it, named by public key. |
| `iat` | no | Issued at, Unix epoch seconds. |
| `exp` | no | Expires at. Optional in AP2, and strongly worth setting — see the gap below. |

## On the wire

An SD-JWT: one issuer-signed JWS, then the disclosures, tilde-separated and
tilde-terminated.

```
<issuer JWS>~<disclosure>~<disclosure>~
```

- The JWS is signed **ES256** by the principal, with `typ: example+sd-jwt` and `kid` set
  to the principal. The `kid` is recorded as evidence and is **never** used to choose a
  verification key.
- The claims sit one level down under `delegate_payload`, matching what AP2's SDK emits.
  A mandate carrying them at the top level is also read.
- A disclosure is base64url of `[salt, value]` (array element) or `[salt, name, value]`
  (object property). Its digest is taken over the **received characters**, not over
  anything re-encoded.

**A mandate must be fully disclosed.** RFC 9901 lets a holder drop disclosures and still
verify; the Desk refuses that, because check 3 has to evaluate every constraint the
principal set and a withheld one would leave a mandate that verifies and authorises
strictly more. Adding a disclosure is refused as well, along with a digest that resolves
twice and one that would overwrite a claim already in the clear.

The cost: an issuer using RFC 9901 decoy digests would have its mandates refused. AP2's
SDK does not use them.

## What check 2 decides

In this order, because nothing a mandate says means anything before its signature
verifies:

| # | Question | Refusal |
|:--|:---|:---|
| 1 | Does the principal's signature verify, and is this a well-formed open Checkout Mandate? | `mandate_signature_invalid` |
| 2 | Has it expired? | `mandate_expired` |
| 3 | Does `cnf` name the presenting agent's registered key? | `agent_mandate_mismatch` |

Structural problems — wrong `vct`, no line items, no `cnf`, an unreadable SD-JWT — leave
under `mandate_signature_invalid`. The reason set is closed (ADR-0006) and the PRD lists
three reasons for this check; growing the vocabulary is a deliberate act with a migration
behind it, and the specific sentence is in the trail entry either way. AP2's own
`invalid_mandate` error code is what we would adopt if it ever grows.

### Which key it verifies against

Never the one the mandate names. The chain is:

```
request → (check 1) → agent → registered principal → principal directory → public key
```

Every link is something the Desk established for itself. A validly signed mandate from
principal B, presented by an agent registered to principal A, has no path to B's key.

Enrol a principal before its mandates can be verified:

```python
PrincipalDirectory(pool).enrol(principal_id="principal-asha", public_key=wallet.public_key)
```

Re-enrolling the same key is idempotent; a different key is refused with
`PrincipalConflict`. Rotation is real, and doing it as a side effect of a lookup is not.

## Using it

```python
check = MandateCheck(PrincipalDirectory(pool), trail)

outcome = check.verify(checkout_mandate, presented_by=identity)
outcome.passed          # bool
outcome.mandate         # OpenCheckoutMandate on a pass, None on a refusal
outcome.digest          # MandateDigest naming the presentation; None on a refusal
outcome.reason_code     # None on a pass
outcome.entry           # the audit entry this outcome wrote

payment = check.verify_payment(payment_mandate, presented_by=identity)
payment.mandate         # OpenPaymentMandate on a pass
```

The same three questions either way — they are questions about a mandate rather than
about a kind of mandate. Whether the two *belong together* is check 3's, because the
answer is a constraint inside one of them rather than a property of either.

`presented_by` is check 1's `IdentityOutcome.identity` — an agent the Desk has just
authenticated, not a name a caller supplied.

`digest` is base64url of SHA-256 over the presentation exactly as received. Check 3 needs
it to pair the two mandates and to key the accumulated spend, and re-deriving it there
would mean digesting a string nobody had checked was the one that verified.

## In the trail

Every outcome, pass or refusal, under `check_2_mandate_validity_passed` /
`check_2_mandate_validity_refused`, subject the agent. Evidence always carries what the
mandate claimed beside the principal actually resolved:

```json
{"claimed_principal_id": "principal-someone-else",
 "verified_against": "principal-asha",
 "algorithm": "ES256"}
```

That is a forged mandate, and it is all there is: nothing about it was proven, so nothing
about its contents is recorded as though it had been. Once the signature verifies, the
mandate's own fields join it — this is a `mandate_expired` refusal:

```json
{"claimed_principal_id": "principal-asha",
 "verified_against": "principal-asha",
 "algorithm": "ES256",
 "key_binding": {"jwk": {"crv": "Ed25519", "kty": "OKP", "x": "H3MBLIoBxkjdp2xSsmWEDgOi4dojij75qpGfQr2Uawo"}},
 "expires_at": "2026-08-29T10:23:32+00:00",
 "presented_at": "2026-08-29T10:24:32.426643+00:00"}
```

"Expired" is an assertion until both instants are in the entry.

## Interoperating

Both directions are tested against Google's SDK at commit `e1ea56d`
(`tests/mandate/test_ap2_interop.py`). The SDK's pins are all exact, so it is **not** a
dependency or an extra of this project — declaring it would drag the whole project down
to `cryptography==46.0.5`. Build a throwaway environment instead:

```
uv venv .venv-conformance --python 3.11
uv pip install --python .venv-conformance/Scripts/python.exe     "psycopg[binary,pool]>=3.2" "pyjwt[crypto]>=2.10" "pytest>=8.3" "pgserver>=0.1.4"     "ap2 @ git+https://github.com/google-agentic-commerce/AP2@e1ea56db72a6385bce3e5c1112b3a56ce60acb43"
.venv-conformance/Scripts/python.exe -m pytest
```

It comes from the repository rather than PyPI, where `ap2` is a third party's mirror of
the superseded v0.1 model under a different licence. Without it those tests skip and say
so.

Two boundaries to know about, both of which check 4 will meet:

- The Desk binds mandates to the agent's **Ed25519** key, which the SDK carries intact on
  a root mandate but whose `JsonWebKey` model would reject on a delegation hop. ADR-0002
  records why that trade was taken.
- A presentation carrying a trailing key-binding JWT, or an AP2 delegation chain joined
  by `~~`, is recognised and refused with a sentence saying the Desk reads the root
  mandate only. Reading either means reading a nonce and an audience, which is check 4.

---

## What this is not

- **Not spend authority.** Whether the amount asked for is inside the constraints, and
  the `payment.budget` ceiling drawn down across deals, is check 3 —
  [docs/spend-authority.md](spend-authority.md).
- **Not freshness.** A mandate presented twice passes here twice. Check 4 owns the nonce
  and the window, which live on the presentation hop rather than on the mandate.
- **Not the closed mandate.** The specific negotiated deal is a later ticket.
- **A known gap until check 4 lands.** `exp` is optional in AP2, so a mandate without one
  never expires by this test. What is meant to bound it is the freshness window on the
  presentation, which does not exist yet.
