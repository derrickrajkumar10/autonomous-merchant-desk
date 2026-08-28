# AP2 mandate model — primary-source research

**Question:** what does Google's Agent Payments Protocol (AP2) actually specify about mandates,
and where does that contradict what `CONTEXT.md`, `PRD.md` and the ADRs already assume?

**Date of research:** 2026-08-28.

## Sources used (primary only)

| Source | What it is | How it was read |
|---|---|---|
| `https://github.com/google-agentic-commerce/AP2` | The official repository. Verified via `gh api repos/google-agentic-commerce/AP2`: `full_name: google-agentic-commerce/AP2`, `license: Apache-2.0`, `homepage: https://ap2-protocol.org/`. | Cloned with `gh repo clone` and read from disk. Head commit `e1ea56db72a6385bce3e5c1112b3a56ce60acb43` (2026-04-29). |
| `https://ap2-protocol.org/ap2/specification/` | The published specification. | `WebFetch`. Confirmed the live site renders the same document as `docs/ap2/specification.md` in the repo, headed **"Agentic Payment Protocol (v0.2)"**. |
| `code/sdk/schemas/ap2/*.json` | The canonical JSON Schemas. The prose docs render their field tables from these via a `{{ schema_fields(...) }}` macro, so **the schemas are the normative field list**, not the prose. | Read from the clone. |
| `code/sdk/python/ap2/` | The official Python SDK source. | Read from the clone. |
| `https://pypi.org/pypi/ap2/json` | Checked to see whether Google publishes an `ap2` package. It does not — see §8. | `WebFetch`. |

**Disclosure, as requested:** `gh` (GitHub CLI, authenticated as `derrickrajkumar10`) was used to verify
repository ownership/metadata and to clone the repository. All file-path-and-line citations below refer
to that clone at commit `e1ea56d`. No blog posts, tutorials or secondary summaries were used.

---

# Where our assumptions are contradicted

Five of them, and the first is structural rather than a detail.

### C1. The Intent Mandate no longer exists in the specification. AP2 v0.2 has **two** mandate types, not three.

**Our claim** — `CONTEXT.md` §4 ("AP2 concepts we reuse") lists three: *Intent Mandate*, *Cart /
Checkout Mandate*, *Payment Mandate*. `PRD.md` FR-1.3 says "Structure follows AP2's Intent Mandate."
`PRD.md` §10 step 3 says "Mandate model (AP2 Intent / Cart / Payment)".

**What the spec says** — `docs/ap2/specification.md:106-107`:

> AP2 defines two Mandate types: Checkout Mandate and Payment Mandate.

There is no Intent Mandate and no Cart Mandate anywhere in `docs/ap2/`. The role our Intent Mandate
plays — a human pre-authorising constraints for a future purchase — is filled by the **open Checkout
Mandate** (`vct: mandate.checkout.open.1`) and the **open Payment Mandate**
(`vct: mandate.payment.open.1`). "Cart Mandate" was renamed to **Checkout Mandate**.

**Why the confusion is understandable, and where the old model still lives:** `IntentMandate` and
`CartMandate` are AP2 **v0.1** (`CHANGELOG.md`: `0.1.0 (2025-09-16)`). v0.2 shipped `2026-04-28`
(`CHANGELOG.md`, "Release of V2"). The v0.1 Pydantic models are *still in the repo* at
`code/sdk/python/ap2/models/mandate.py:28-30`:

```python
CART_MANDATE_DATA_KEY = 'ap2.mandates.CartMandate'
INTENT_MANDATE_DATA_KEY = 'ap2.mandates.IntentMandate'
PAYMENT_MANDATE_DATA_KEY = 'ap2.mandates.PaymentMandate'
```

and in the Go sample at `code/samples/go/pkg/ap2/types/mandate.go:21-35`. So a reader who greps the
repo finds the three-mandate model and concludes it is current. It is not — it is the superseded
v0.1 sample layer, and the v0.2 specification directory (`docs/ap2/`) does not mention it.

**Impact:** `CONTEXT.md` §4, `PRD.md` FR-1.3, FR-5.6, §10 step 3 and FR-11.3 all need their
vocabulary updated, or need an explicit sentence saying we are deliberately modelling on AP2 v0.1.
Either is defensible. Saying "we adopt AP2's mandate model" while naming three mandates that v0.2
deleted is the thing that will not survive the panel round.

### C2. AP2 **does** bind mandates to the specific agent — via a mandatory `cnf` claim. CONTEXT.md §4 is wrong.

**Our claim** — `CONTEXT.md` §4: "AP2 also binds mandates to the **user, not the agent** — agent
identity is explicitly out of scope for AP2. That gap is where our agent-identity registry and
reputation ladder live." The table row reads "Agent identity attestation | Visa TAP | AP2
deliberately leaves this out — **we fill it**".

**What the spec says** — `docs/ap2/security_and_privacy_considerations.md:34-35`, as the stated
mitigation for the threat "An attacker reuses an open Payment Mandate with a different closed
Payment Mandate":

> Open Mandates MUST contain the Agent's key (via a `cnf` claim) so that only the agent could create
> a Closed Mandate with a valid signature.

And `docs/ap2/specification.md:224-226`:

> These MUST include the agent's public key as a `cnf` claim. This is required as it is not yet bound
> to a particular transaction, and so it needs to be constrained for use by the Agent.

`cnf` is a **required** property in both open-mandate schemas — `code/sdk/schemas/ap2/open_checkout_mandate.json`
and `code/sdk/schemas/ap2/open_payment_mandate.json` both list `"required": ["vct", "constraints", "cnf"]`.
It is an RFC 7800 proof-of-possession key reference ("Confirmation claim defined in RFC 7800 section
3.1. Used for key binding.").

`docs/ap2/agent_authorization.md:394-399` makes the intent explicit — an open Mandate is
"bound to a particular Agent who is allowed to use the Mandate."

**Impact — this is the important one.** `PRD.md` **FR-1.4** ("The mandate names the agent permitted
to present it. A stolen mandate must not work for a different agent") is presented as our extension.
It is not: it is AP2's `cnf` claim, and AP2 makes it a MUST. The mechanism is stronger than "names
the agent" too — `cnf` carries the agent's *public key*, and the closed mandate is only valid if
signed by the matching private key, so a stolen open mandate is useless without the agent's key
rather than merely mismatched on an identifier.

This does **not** kill our agent-identity work. What AP2 leaves out is genuinely: *who is this agent,
is it registered, what is its reputation, what ceiling does it get* — none of which AP2 addresses.
But the specific sentence "AP2 binds mandates to the user, not the agent" is false, and FR-1.4 should
be reframed as *"we implement AP2's `cnf` key-binding, and add a registry and reputation ladder on
top"* rather than as filling a gap AP2 left. Claiming AP2's own MUST as our innovation is exactly the
kind of thing an architecture panel catches.

### C3. AP2 **does** have a partial-spend / drawn-down-balance concept: the `payment.budget` constraint. ADR-0004's premise is wrong; its conclusion is right.

**Our claim** — the task brief states the project has decided AP2 has no concept of partial spend.
`CONTEXT.md` §10 records "Partial spend vs AP2 — resolved." ADR-0004 says partial-spend accounting
"is a real extension of AP2 and must be documented as such under FR-11.3."

**What the spec says** — `code/sdk/schemas/ap2/open_payment_mandate.json`, `$defs.budget`:

```json
"budget": {
  "type": "object",
  "description": "Defines the maximum total amount that can be spent when using the payment.agent_recurrence constraint.",
  "required": ["type", "max", "currency"],
  "properties": {
    "type":     { "const": "payment.budget" },
    "max":      { "type": "number", "description": "Maximum amount for the budget." },
    "currency": { "type": "string", "description": "ISO4217 Alpha-3 defining the currency of the amount." }
  }
}
```

And the evaluation rule, `docs/ap2/payment_mandate.md:202-207`:

> **Evaluation**: Evaluating the budget requires tracking the total amount spent using this Payment
> Mandate. For this constraint to evaluate as true, the requested amount plus the total sum of amounts
> from previously closed Payment Mandates MUST be less than or equal to `max`. After approval, the
> amount MUST be added to the accumulated total for future evaluation.

That is a remaining balance drawn down against a mandate, specified normatively, with a MUST.
It pairs with `payment.agent_recurrence` (`frequency` ∈ `ON_DEMAND | DAILY | WEEKLY | BIWEEKLY |
MONTHLY | QUARTERLY | ANNUALLY`, plus optional `max_occurrences`), whose evaluation
(`docs/ap2/payment_mandate.md:58-63`) likewise "requires tracking the previous presentations of
Payment Mandates associated with this open one."

**But note what AP2 does *not* do, which vindicates ADR-0004's actual decision.** The mandate is
still an immutable signed credential. Nothing in either schema carries a mutable `remaining` field.
The accumulated total is **verifier-side state** — the spec says the verifier tracks it and adds to
it after approval. That is structurally identical to ADR-0004's "the balance is Desk-side ledger
state keyed by mandate ID; the mandate stays immutable and single-signed."

**Impact:** ADR-0004's *decision* is correct and should stand unchanged. Its *framing* is wrong in
two places and should be edited:

- "rather than extending AP2's mandate to carry it" — AP2 never proposed carrying it; the alternative
  ADR-0004 rejects is not one AP2 offered.
- "This is a real extension of AP2 and must be documented as such under FR-11.3" — it is **not** an
  extension. It is what `payment.budget` already specifies. FR-11.3 should say we *implement* the
  `payment.budget` constraint, which is a considerably stronger claim than "we extended the standard,"
  and it comes with a spec-defined evaluation algorithm we can point at.

There is a real design decision left over: whether our `exceeds_remaining_balance` refusal keys off a
`payment.budget` constraint carried in the mandate, or off a ceiling we store out-of-band. The former
is interoperable; the latter is not.

### C4. AP2 forbids Ed25519 for the Checkout JWT. ADR-0002 says Ed25519 for *all* signing.

**Our claim** — ADR-0002, referenced from `CONTEXT.md` §8: "**JSON Web Signatures over Ed25519** for
all signing."

**What the spec says** — `docs/ap2/specification.md:154-157`:

> The Payment Mandate is bound to a particular Checkout using the cryptographic hash of the Checkout
> JWT. To prevent rainbow table attacks, the Checkout JWT MUST be signed using a digital signature
> scheme (e.g., ECDSA) and **not a deterministic signature (e.g., Ed25519).**

The reasoning is spelled out at `docs/ap2/security_and_privacy_considerations.md:143-148`: the
`checkout_hash` relies on entropy contributed by the signature itself to stop an attacker guessing
checkout contents by brute force. A deterministic signature contributes none, so:

> If a signing algorithm (e.g. deterministic signature scheme such as `Ed25519`) is used that does not
> include this then a salt of sufficient entropy MUST be present in the Checkout.

Every algorithm actually used in the official SDK is **ES256** (ECDSA P-256 / SHA-256), not EdDSA:
`code/sdk/python/ap2/sdk/jwt_helper.py:27` — `jws.add_signature(private_key, alg='ES256', ...)`;
`code/sdk/python/ap2/sdk/generated/types/jwk.py:57-59` — `alg: Literal['ES256']`, described as
"Algorithm. Must be 'ES256' for P-256 curve signing." Every worked example in the spec uses
`"alg": "ES256"`.

**Impact:** this is narrow but real, and it lands on our sell side. FR-5.6 produces a Cart/Checkout
Mandate; if the Desk signs the checkout object with Ed25519 as ADR-0002 mandates, it violates an AP2
MUST *unless* we add an explicit entropy salt to the checkout payload. Two honest options: (a) sign
the merchant checkout object with ES256 and keep Ed25519 for agent-request signing and receipts, or
(b) keep Ed25519 everywhere and carry a random salt in the checkout payload, which the spec's own
sentence explicitly permits. Option (b) preserves ADR-0002 and is defensible on camera; either way
ADR-0002 needs a "known exception" paragraph, because "Ed25519 for all signing" as written is
incompatible with the spec we say we adopt.

### C5. "Prompt playback" is not in AP2 v0.2. The nearest field is a v0.1 artefact.

**Our claim** — `CONTEXT.md` §4 lists as an AP2 concept we reuse: the Intent Mandate carries
"'prompt playback' (the agent's natural-language restatement of what the human asked)". `PRD.md`
FR-1.2 builds on this.

**What the spec says** — nothing. The phrase "prompt playback" appears nowhere in AP2, and neither
does any free-text natural-language field. Grepping all of `docs/ap2/*.md` and the four mandate
schemas for `natural language`, `playback`, `restate`, `description` turns up only constraint
descriptions and `error_description` on the Mandate Receipt (`docs/ap2/agent_authorization.md:516`).
The v0.2 mandates carry *machine-evaluable constraints*, not prose.

The field our concept maps to exists only in **v0.1**, at
`code/sdk/python/ap2/models/mandate.py:47-55`:

```python
natural_language_description: str = Field(
    ...,
    description=(
        "The natural language description of the user's intent. This is"
        ' generated by the shopping agent, and confirmed by the user. The'
        ' goal is to have informed consent by the user.'
    ),
    example='High top, old school, red basketball shoes',
)
```

(also `code/samples/go/pkg/ap2/types/mandate.go:27`, `NaturalLanguageDescription string`.) It is
required in v0.1, and its stated purpose — informed consent — is exactly ours. But it is gone in
v0.2, where consent is instead obtained by rendering Mandate Content on a **Trusted Surface**
(`docs/ap2/specification.md:49-51`).

**Impact:** FR-1.2 is still a good feature and the voice-capture demo beat is unaffected. But
`CONTEXT.md` §4 should stop citing it as a v0.2 AP2 concept. In v0.2 terms, our wallet *is* the
Trusted Surface, and the prompt playback is what that Trusted Surface renders — a framing that is both
more accurate and better positioned, since AP2 defines the Trusted Surface role but leaves how it
obtains consent open.

---

## Not contradicted — assumptions the spec confirms

Recording these explicitly so the list above is not mistaken for a wholesale rejection.

- **Mandates are signed verifiable credentials.** Confirmed: `docs/ap2/specification.md:398-399` —
  "AP2 specifies the use of `SD-JWT`s for securing the Payment and Checkout Mandates." SD-JWT VC is a
  verifiable-credential format. (The precise format is not W3C VC — see §2.)
- **Mandates carry a timestamp and a nonce, so replay and freshness checks come nearly free.**
  Confirmed, with the detail that these sit in the *key-binding* layer rather than the mandate body —
  see §3.
- **AP2 supports an "open" / human-not-present mode.** Confirmed, and "open" is the spec's own word —
  see §7.
- **AP2 gives the envelope but not a merchant that decides** (`CONTEXT.md` §4). Confirmed, and the
  spec says so itself: `docs/ap2/implementation_considerations.md:101-104` — "Merchants or Trusted
  Surfaces MAY wish to only work with trusted Agents. These details are left to the Commerce Protocol
  layer."
- **The Desk is right to run deterministic checks rather than LLM judgment on signatures**
  (`CONTEXT.md` §5.1, FR-3.1). Strongly confirmed: `docs/ap2/specification.md:96-98` — "When this
  document refers to validation or processing for a particular role, it MUST happen in deterministic
  code regardless of whether the role is agentic or not." And
  `docs/ap2/security_and_privacy_considerations.md:5-8` — "AP2 assumes that preventing prompt
  injection attacks is infeasible. Therefore, all LLMs and Agents MUST be considered potential
  attackers and are explicitly included in the threat model."
- **Signed receipts binding the mandate chain** (FR-7.2). Confirmed and specified — see §2.
- **A2A as transport.** Confirmed as compatible; the samples are built on A2A. AP2 v0.2 additionally
  positions itself against **UCP** (Universal Commerce Protocol) —
  `docs/ap2/specification.md:22-24`.

---

## 1. Exact field structure of the mandates

Read from the canonical JSON Schemas in `code/sdk/schemas/ap2/`. The prose docs generate their tables
from these files, so these are authoritative. Note again (C1) that **Intent Mandate and Cart Mandate
do not exist in v0.2**; the four types below are the complete set.

### 1a. Open Checkout Mandate — the closest thing to our "Intent Mandate"

`code/sdk/schemas/ap2/open_checkout_mandate.json`. `vct` const `mandate.checkout.open.1`.

| Field | Type | Required | Notes |
|---|---|---|---|
| `vct` | string | **required** | const `"mandate.checkout.open.1"` |
| `constraints` | array | **required** | Items are `allowed_merchants` or `line_items`. Schema-level `"contains": {"$ref": "#/$defs/line_items"}` — **at least one `checkout.line_items` constraint is mandatory**. |
| `cnf` | object | **required** | "Confirmation claim defined in RFC 7800 section 3.1. Used for key binding." Holds the agent's public JWK. |
| `iat` | integer | optional | "The creation timestamp as a Unix epoch." |
| `exp` | integer | optional | "The expiration timestamp as a Unix epoch." |

Constraint `checkout.allowed_merchants`: required `type`, `allowed` (array of `Merchant`,
`x-selectively-disclosable-array`).

Constraint `checkout.line_items`: required `type`, `items` (array, `minItems: 1`) of
`line_item_requirements` — required `id` (string), `acceptable_items` (array of `item`,
`x-selectively-disclosable-array`), `quantity` (integer, `exclusiveMinimum: 0`).
`item`: required `id` (string, "Will often be the SKU"), `title` (string).

### 1b. Closed Checkout Mandate — our "Cart Mandate", the negotiated deal

`code/sdk/schemas/ap2/checkout_mandate.json`. `vct` const `mandate.checkout.1`.

| Field | Type | Required | Notes |
|---|---|---|---|
| `vct` | string | **required** | const `"mandate.checkout.1"` |
| `checkout_jwt` | string | **required** | "base64url-encoded serialized merchant-signed JWT of the Checkout payload." `x-selectively-disclosable-field: true` |
| `checkout_hash` | string | **required** | "base64url-encoded hash of the checkout_jwt field value, uniquely identifying this checkout." Algorithm MUST match `_sd_alg`, else `sha-256`. |
| `iat` | integer | optional | |
| `exp` | integer | optional | |

The contents of `checkout_jwt` are **deliberately out of scope** —
`docs/ap2/checkout_mandate.md:30-33`: "The details of the payload are outside the scope of this
specification, when used with the Universal Commerce Protocol this MUST be the Checkout object." So
our negotiated terms, margin and levers live inside a payload AP2 does not constrain. Good news for
FR-5.6: we may put whatever we like in there.

### 1c. Open Payment Mandate

`code/sdk/schemas/ap2/open_payment_mandate.json`. `vct` const `mandate.payment.open.1`.

Required: `vct`, `constraints`, `cnf`. Schema-level `"contains": {"$ref": "#/$defs/payment_reference"}`
— **a `payment.reference` constraint is mandatory.** Optional: `payee`, `payment_amount`,
`payment_instrument`, `pisp`, `execution_date`, `risk_data`, `iat`, `exp`. Additionally,
`docs/ap2/payment_mandate.md:26-27`: "The open Payment Mandate MAY optionally include any property
from the closed Payment Mandate."

Eight constraint types, all with `type` as a required const discriminator:

| `type` | Required properties | Optional | Evaluation (`docs/ap2/payment_mandate.md`) |
|---|---|---|---|
| `payment.agent_recurrence` | `frequency` (enum: `ON_DEMAND`, `DAILY`, `WEEKLY`, `BIWEEKLY`, `MONTHLY`, `QUARTERLY`, `ANNUALLY`) | `max_occurrences` (int) | Requires tracking previous presentations; time-separation + occurrence count (L58–63) |
| `payment.allowed_payees` | `allowed` (array of `Merchant`, selectively disclosable) | — | `payee` MUST be present in `allowed` (L86–88) |
| `payment.allowed_payment_instruments` | `allowed` (array, selectively disclosable) | — | `payment_instrument` MUST be in `allowed` (L114–116) |
| `payment.allowed_pisps` | `allowed` (array of PISP) | — | facilitating PISP MUST be in `allowed` (L152–153) |
| `payment.amount_range` | `currency` (ISO4217 alpha-3), `max` (int, **minor units**) | `min` (int) | `payment_amount` within range; currency MUST match (L177–180) |
| `payment.budget` | `max` (number), `currency` | — | Running total; see C3 (L202–207) |
| `payment.execution_date` | — (only `type`) | `not_before`, `not_after` | `execution_date` within window (L254–257) |
| `payment.reference` | `conditional_transaction_id` (string) | — | "Digest of the associated Open Checkout Mandate" (L231–235) |

Note the units inconsistency in AP2 itself: `payment.amount_range.max` is an integer in **minor
units**, while `payment.budget.max` is a `number` with no stated unit. Worth pinning down in our own
implementation rather than assuming.

### 1d. Closed Payment Mandate

`code/sdk/schemas/ap2/payment_mandate.json`. `vct` const `mandate.payment.1`.

| Field | Type | Required | Notes |
|---|---|---|---|
| `vct` | string | **required** | const `"mandate.payment.1"` |
| `transaction_id` | string | **required** | "base64url-encoded hash of the checkout_jwt field value, uniquely identifying the checkout associated with this." Same algorithm as `sd_hash`, else sha256. **This is the Payment→Checkout link.** |
| `payee` | `types/merchant.json` | **required** | |
| `payment_amount` | `types/amount.json` | **required** | `{currency: ISO4217, amount: integer minor units}` — e.g. `27999 = $279.99` |
| `payment_instrument` | `types/payment_instrument.json` | **required** | |
| `pisp` | `types/pisp.json` | optional | |
| `execution_date` | string | optional | ISO8601. "When absent indicates immediate execution." |
| `risk_data` | object | optional | "A map of relevant risk signals collected by the trusted surface at time of mandate creation." |
| `iat` | integer | optional | |
| `exp` | integer | optional | |

### 1e. Receipts

Both mandate types have a receipt (`code/sdk/schemas/ap2/checkout_receipt.json`,
`payment_receipt.json`). The generic Mandate Receipt shape is specified at
`docs/ap2/agent_authorization.md:503-519` — a **Verifier-signed JWT**:

- `iss` — **REQUIRED**, MUST be the Verifier.
- `result` — **REQUIRED**, enum `["success", "error"]`.
- `reference` — **REQUIRED**, base64url hash of the received Mandate; over a chain it is the hash of
  the *final* SD-JWT, computed as `sd_hash` is.
- `error` — OPTIONAL, MUST be present when `result` is `"error"`.
- `error_description` — OPTIONAL, human-readable.

Defined error codes (`docs/ap2/agent_authorization.md:521-535`): `invalid_credential`,
`unresolved_constraint`, `invalid_mandate`, `mandates_not_supported`. **These map directly onto our
`reason_code` enum in ADR-0006** and are worth adopting verbatim where they fit — a refusal that
names an AP2-defined error code is a stronger demo line than one that names only our own.

---

## 2. Signing and chaining

### Credential format: SD-JWT VC, not W3C Verifiable Credentials

`docs/ap2/specification.md:396-401`:

> AP2 specifies the use of `SD-JWT`s for securing the Payment and Checkout Mandates. Payment and
> Checkout Mandates could be cryptographically secured by other VDCs as mentioned in Agent
> Authorization.

Normative reference (`docs/ap2/agent_authorization.md:542`): **RFC 9901**, "Selective Disclosure for
JWTs (SD-JWT)", February 2025. Also normative: **OpenID4VP**, **RFC 7800** (proof-of-possession key
semantics — the `cnf` claim), and **Delegate SD-JWT** (an *individual draft*, `GarethCOliver/gco-delegate-sd-jwt`,
2026 — worth flagging as the one load-bearing dependency that is not a ratified standard).

`docs/ap2/agent_authorization.md:429-431` notes ISO mDocs COULD be used instead. **W3C Verifiable
Credentials are never mentioned.** If our docs say "W3C Verifiable Credentials", that is inaccurate,
though "signed verifiable credentials" as `CONTEXT.md` §4 phrases it is fine — the spec's own glossary
term is "Verifiable digital credential (VDC)".

### Signature algorithms

The prose specifies a *class* of algorithm rather than an allowlist. The one hard rule is the
prohibition in C4 (`docs/ap2/specification.md:154-157`): the Checkout JWT MUST use a non-deterministic
scheme, e.g. ECDSA, and not Ed25519.

In the code and every worked example the algorithm is **ES256**:

- `code/sdk/python/ap2/sdk/jwt_helper.py:16,27` — "Create a compact JWS (ES256)";
  `jws.add_signature(private_key, alg='ES256', protected=json.dumps(header))`
- `code/sdk/python/ap2/sdk/generated/types/jwk.py:57-59` — `alg: Literal['ES256']`, "Must be 'ES256'
  for P-256 curve signing."
- `docs/ap2/agent_authorization.md:158-161` — the OpenID4VP request advertises
  `"sd-jwt_alg_values": ["ES256"], "kb-jwt_alg_values": ["ES256"]`.

**The spec is silent on** a formal list of permitted signature algorithms. ES256 is what the reference
implementation does and what every example shows; it is not stated as a MUST for mandates generally.

### How the chain is cryptographically linked

Two distinct linking mechanisms, and it is worth keeping them apart:

**(i) Open → Closed, within a mandate type — by key binding and hash chaining.**
`docs/ap2/agent_authorization.md:392-399`: a Closed mandate is produced by "the Agent generating a Key
Binding JWT (Proof-of-Possession) using the key endorsed in the open Mandate's `cnf` claim." Each hop
is a KB-SD-JWT signed by the *previous* hop's `cnf.jwk`, binding backwards via `sd_hash` (covers the
preceding JWT **and** its disclosures) or `issuer_jwt_hash` (covers only the preceding JWT, letting the
next delegate redact further). Wire format, `code/sdk/python/ap2/sdk/README.md`:

```
<root_SD-JWT>~<disc…>~~<KB-SD-JWT+KB_1>~<disc…>~~…~~<closed_KB-SD-JWT>~<disc…>~
```

Hops joined by `~~`. `typ=kb+sd-jwt+kb` for intermediate hops (payload contains `cnf`, further
delegation possible); `typ=kb+sd-jwt` for the terminal closed mandate (MUST NOT carry `cnf`). Verified
by `code/sdk/python/ap2/sdk/sdjwt/chain.py::verify_chain`, which walks the chain and follows `cnf`.
Chains are of arbitrary depth. The verifier trusts **only the root issuer key**; every subsequent hop
is validated by the preceding hop's `cnf.jwk`.

**(ii) Checkout ↔ Payment, across mandate types — by hash reference.**

- Closed Payment Mandate `transaction_id` = the hash of `checkout_jwt`
  (`code/sdk/schemas/ap2/payment_mandate.json`). This is what ties a payment to its checkout.
- Open Payment Mandate carries a mandatory `payment.reference` constraint whose
  `conditional_transaction_id` is the "Digest of the associated Open Checkout Mandate"
  (`docs/ap2/payment_mandate.md:231-235`).
- Closed Checkout Mandate `checkout_hash` = hash of the merchant-signed `checkout_jwt`.
- Receipt `reference` = `sha256` of the closed leaf JWT, which is how a receipt binds back to the
  authorised mandate. Canonically:
  `reference = compute_sha256_b64url(MandateClient().get_closed_mandate_jwt(chain))`
  (`code/sdk/python/ap2/sdk/README.md`).

So the v0.2 chain is: **root-issuer SD-JWT (open mandate, `cnf` = agent key) → [zero or more KB-SD-JWT
delegation hops] → closed mandate (KB-SD-JWT, `sd_hash` binds the whole preceding chain) → Verifier
receipt (`reference` = hash of the closed leaf).** Our three-step "Intent → Cart → Payment" is not
that shape; it is two *parallel* two-step chains (open→closed checkout, open→closed payment) joined by
`transaction_id`/`checkout_hash`.

### Verification and processing rules

`docs/ap2/agent_authorization.md:455-465`:

> 1. Verify and process the SD-JWT chain according to [Delegate SD-JWT].
> 2. Extract claims from open Mandate Content and verify the closed Mandate Content has these values
>    unchanged.
> 3. Extract each Constraint from each open Mandate Content and evaluate them against the closed
>    Mandate Content based on the Constraint Type.
>     - Any unknown Constraints MUST be treated as failing evaluation.

That last line is a fail-closed rule worth stealing verbatim for our check 3, and it sits well beside
`CONTEXT.md` principle 4.

---

## 3. Nonce, timestamp, TTL/expiry, signer key reference

All four exist. The important structural point: **`iat`/`exp` live on the mandate; `nonce`/`aud` live
on the key-binding hop, not on the mandate body.** Our check 4 ("nonce unseen, timestamp inside
window") therefore reads two different layers.

| Concept | Field name | Where | Required? |
|---|---|---|---|
| Creation timestamp | **`iat`** | Mandate body (all four schemas). Also on every KB-SD-JWT hop. | *Optional* in the mandate schemas. **Required** on KB hops — `code/sdk/python/ap2/sdk/sdjwt/kb_sd_jwt.py:74` sets `'iat': int(time.time())` unconditionally; verification "checks `iat` is present" (L107). |
| TTL / expiry | **`exp`** | Mandate body. "The expiration timestamp as a Unix epoch." | *Optional* in the schemas. But `docs/ap2/specification.md:227-229`: "It is RECOMMENDED to set the `exp` claim for these Mandates to the smallest value that will allow the Shopping Agent to complete the assigned task." |
| Nonce | **`nonce`** | KB-SD-JWT hop payload, **not** the mandate body. Supplied by the verifier as a challenge. | **Required** at every hop: `kb_sd_jwt.py:62-63` — `if not aud or not nonce: raise ValueError('aud and nonce are required for KB-SD-JWT hops')`. |
| Audience | **`aud`** | KB-SD-JWT hop payload. Example value `"merchant"`. | Same MUST as `nonce`. |
| Signer key reference | **`cnf`** (containing `cnf.jwk`) | Open mandate body. RFC 7800 proof-of-possession key. | **Required** on open mandates (schema `required` array). MUST NOT be present on a terminal closed mandate — `kb_sd_jwt.py:137`: `"Terminal KB-SD-JWT MUST NOT carry a 'cnf' claim"`. |
| Key id | **`kid`** | JWS header. Example: `"kid": "agent-provider-key-1"`. | Not specified as required. `code/sdk/python/ap2/sdk/sdjwt/chain.py` also supports `x5c` certificate-chain resolution via `X5cOrKidPublicKeyProvider`. |
| Binding hash | **`sd_hash`** or **`issuer_jwt_hash`** | KB-SD-JWT hop payload. | One of the two required per hop. |

`docs/ap2/agent_authorization.md:433-447` gives the generic Mandate Content claim list: `vct`
**REQUIRED**; `constraints` **OPTIONAL** (each with a REQUIRED `type`); `cnf` **OPTIONAL** in general
but "**REQUIRED** if the Mandate is still open." Plus: "any claim in SD-JWT-VC MAY also be used" —
which is where `iat`/`exp`/`nbf` come from.

**Where the spec is silent:** on nonce *length*, entropy, or format; on how long a verifier must retain
seen nonces; and on any clock-skew window for `iat`. Our FR-3.4 "short configurable window" is our own
choice, correctly so.

---

## 4. Partial spend

**Refuted as stated — see C3 above for the full finding.** In brief: AP2 has `payment.budget`
(`max` + `currency`), whose normative evaluation at `docs/ap2/payment_mandate.md:202-207` is a running
total accumulated across previously closed Payment Mandates, plus `payment.agent_recurrence`
(`frequency`, `max_occurrences`) for how often a mandate may be re-presented. AP2 also anticipates
recurrence being reduced by receipts — `docs/ap2/agent_authorization.md:498-501`: "The agent reduces
the scope of the open mandate based on the receipt, often preventing future presentations entirely."

Two further points that matter for us:

**A default single-use rule.** `docs/ap2/specification.md:237-240`:

> Shopping Agents MUST NOT present any subsequent open Payment or Checkout Mandates without receiving
> a rejection receipt from the previous one. This is to prevent an Agent approving multiple different
> Checkouts using the same open Mandate.

So AP2's *default* is one-shot; `payment.agent_recurrence` is the explicit opt-in to reuse. Our
partial-spend model assumes reuse by default. That is a divergence to state, not a contradiction — but
it means an AP2-conformant external buyer agent (FR-11.1) would not re-present a mandate after a
success receipt unless we issue mandates carrying `agent_recurrence`.

**Who holds the counter.** `docs/ap2/security_and_privacy_considerations.md:104-112` puts double-spend
prevention on the agent's deterministic code, then adds: "Credential Provider, Networks or MPPs **MAY**
reject multiple overlapping Mandates". MAY, not MUST — which is exactly the gap ADR-0004 fills on the
merchant side. Our decision to hold the authoritative counter merchant-side and never trust a
counterparty's claim about what remains is *more* conservative than AP2 requires, and that is a good
line to have ready.

**The spec is silent on** partial fulfilment of a single checkout (buying some of a cart and returning
the rest to the balance). The `checkout.line_items` evaluation explicitly excludes it —
`docs/ap2/checkout_mandate.md:107-110`: "This evaluation does not support splitting the open Checkout
Mandate across multiple Checkouts. Future constraint extensions can add this support, but consideration
must be given to how multiple duplicate orders can be prevented."

---

## 5. Agent binding

**Refuted — see C2 above for the full finding.** AP2 requires the agent's public key in the open
mandate's `cnf` claim, and a closed mandate is only valid if signed by the matching private key. A
stolen open mandate is unusable by a different agent. This is precisely FR-1.4, and it is AP2's, not
ours.

The genuine gap is narrower and still ours: AP2 binds a mandate to *a* key, but says nothing about who
owns that key, whether it is registered, or what it has done before. `docs/ap2/implementation_considerations.md:101-104`
hands that off explicitly:

> AP2 is designed to constrain Agent behaviors without them having to be inherently trustworthy. As
> part of implementing a Commerce Protocol, Merchants or Trusted Surfaces MAY wish to only work with
> trusted Agents. These details are left to the Commerce Protocol layer.

That sentence is the correct citation for our agent-identity registry, trust score and spend ceiling —
AP2 naming the layer and declining to fill it. It is a better citation than the one `CONTEXT.md` §4
currently implies, because it is the spec conceding the gap in its own words.

**The spec is silent on** agent identity attestation, agent reputation, and any registry. It does not
mention Visa TAP or any competing attestation scheme anywhere in `docs/`.

---

## 6. "Prompt playback"

**Not in v0.2 — see C5 above.** The term does not appear in AP2 at any version. The concept exists
only as v0.1's `IntentMandate.natural_language_description`
(`code/sdk/python/ap2/models/mandate.py:47-55`, required, purpose stated as "informed consent by the
user"; Go equivalent `NaturalLanguageDescription` at `code/samples/go/pkg/ap2/types/mandate.go:27`).
v0.2 replaced free-text consent with machine-evaluable `constraints` rendered on a **Trusted Surface**.

**The spec is silent on** what a Trusted Surface must display. `docs/ap2/specification.md:49-51`
defines it only as "a UI surface that is trusted to get informed user consent for an Intent before
creating a user-signed Mandate", and `docs/ap2/specification.md:78-80` requires it to be non-agentic.
Our prompt playback is therefore a legitimate implementation of a role AP2 defines but leaves open —
which is a stronger position than reusing a deleted field.

---

## 7. Human-not-present / "open" mode

First-class in v0.2, and "open" is the spec's own vocabulary. `docs/ap2/specification.md:166-176`:

> There are two `modes` that AP2 can consider to operate in.
>
> - Human Present (Direct): The User directly sees the closed Checkout and approves it and its payment
>   explicitly.
> - Human Not Present (Autonomous): The User sees and approves a set of constraints over what closed
>   Checkout and Payment would meet their intent. The Shopping Agent then assembles and approves a
>   closed Checkout and Payment Mandate on their behalf using these open Mandates.

How it is expressed in the mandate — there is no `mode` field. The mode is carried by **which `vct`
you use** and **who signed the closed mandate**:

- Human present: user signs the closed mandate directly (`mandate.checkout.1`, `mandate.payment.1`).
- Human not present: user signs an **open** mandate (`mandate.checkout.open.1`,
  `mandate.payment.open.1`) carrying `constraints` + `cnf` (+ RECOMMENDED short `exp`); the agent later
  signs the closed mandate with the key named in `cnf`, and presents the whole chain.

`docs/ap2/specification.md:178-190`:

> Verifiers of Mandates *always* receive a closed Payment and Checkout Mandate, regardless of the mode.
> The difference is only in how the verification of the Mandate is performed. […] In the Autonomous
> case, the closed Mandates are signed by an Agent key. Trust in this key is provided by open Mandates
> that are signed by the User […]

A detail with real consequences for our Desk: **the verifier always sees a closed mandate.** Whether
a human was present is inferred from the chain's shape and signers, not read off a flag. If our
audit trail wants to record "delegated" vs "direct", we derive it — we do not read it.

Note also `docs/ap2/specification.md:256-260`: "Conceptually, it is possible to use this protocol to
support delegation of Mandates from one Shopping Agent to another. This is outside the scope of the
current specification." Relevant if we ever chain buyer→sub-agent.

The v0.1 equivalent flag was `IntentMandate.user_cart_confirmation_required: bool`
(`code/sdk/python/ap2/models/mandate.py:38-45`), defaulting `True`, with "This must be true if the
intent mandate is not signed by the user." That field does not exist in v0.2.

---

## 8. Official Python library / reference implementation

**Status: an SDK plus samples, in a repository whose own README calls itself samples and demos. Not
production-ready, and not on PyPI.**

| Question | Answer | Source |
|---|---|---|
| Import name | `ap2` | `code/README.md`: "the package exposed by the root `pyproject.toml` (installed as `import ap2`)" |
| Distribution name | `ap2` | root `pyproject.toml`: `name = "ap2"` |
| Version | **`0.1`** | root `pyproject.toml`: `version = "0.1"` — note this lags the v0.2 spec; `CHANGELOG.md` records `0.2.0 (2026-04-28)` "Release of V2" |
| Install | From the repo. `[tool.setuptools.packages.find] where = ["code/sdk/python"]`. There is **no official Google `ap2` package on PyPI.** | root `pyproject.toml`; PyPI check below |
| Python | `>=3.11` | root `pyproject.toml` |
| Dependencies | `cryptography==46.0.5`, `jwcrypto==1.5.6`, `pydantic==2.12.5`, `sd-jwt==0.10.4`, `pytest==9.0.2` — all **pinned exactly**, which is a sample-repo smell, not a library one | root `pyproject.toml` |
| Licence | Apache-2.0 | `LICENSE`; `gh api` metadata |

**PyPI warning.** `https://pypi.org/pypi/ap2/json` resolves to a package named `ap2` at version
`0.1.1` (3 Oct 2025), author **`whill`**, licensed **MIT**, whose own description states it is
"**not an official Google product**" and merely "aligns with and mirrors content from the official AP2
repository". **`pip install ap2` does not install Google's code.** It installs a third-party mirror of
the superseded v0.1 model, under a different licence. If we vendor or depend on AP2 code, take it from
the GitHub repository, and say so in FR-11.3.

**What is in the box:**

- `code/sdk/python/ap2/sdk/` — the real runtime: `MandateClient` (`create` / `present` / `verify`),
  `ReceiptClient`, `sdjwt/` (RFC 9901 SD-JWT + KB-SD-JWT + arbitrary-depth chain verification),
  `constraints.py`, `payment_mandate_chain.py`, `checkout_mandate_chain.py`, `max_flow_helper.py`
  (Dinic / Edmonds-Karp, for the `checkout.line_items` maximal-flow evaluation). This is genuinely
  useful and directly reusable.
- `code/sdk/python/ap2/models/` — the **v1 Pydantic models** (`IntentMandate`, `CartMandate`,
  `PaymentMandate`). Superseded; do not build on these.
- `code/sdk/python/ap2/tests/` — 17 test files including `chain_tests.py`,
  `payment_mandate_chain_tests.py`, `kb_sd_jwt_tests.py`, `constraints_tests.py`.
- `code/samples/` — Python, Go and Android reference roles and runnable scenarios
  (`human-present/cards`, `human-not-present/cards`, `human-present/x402`, `human-not-present/x402`).
- `code/web-client/` — a Vite + React demo UI.

**Production-readiness, in the repo's own words** — `README.md:11`: "This repository contains code
samples and demos of the Agent Payments Protocol." `code/README.md` calls `sdk/` "the primary artifact
of this repository" but `samples/` "reference implementations". The samples depend on Google ADK and
Gemini 3.1 Flash Lite Preview, though `README.md:23-28` is clear that AP2 requires neither.

**Practical read for us:** `ap2.sdk` is worth vendoring for SD-JWT chain verification and constraint
evaluation — it is real, tested code that implements the hard part. The `ap2.models` layer is not.
Note the friction against ADR-0002: the SDK's `jwt_helper` is ES256-only, so signing our mandates with
Ed25519 means not using the SDK's signing path (verification of *incoming* AP2 mandates is unaffected).

---

## Summary of recommended follow-ups

Not decisions — the calls belong to whoever owns these documents.

1. **`CONTEXT.md` §4** — replace the three-mandate list with v0.2's Checkout/Payment × open/closed
   model; delete "AP2 binds mandates to the user, not the agent"; stop citing prompt playback as an
   AP2 concept and recast the wallet as AP2's **Trusted Surface** role.
2. **`PRD.md` FR-1.4** — reframe as *implementing* AP2's `cnf` key binding, with the registry and
   reputation ladder as the layer above.
3. **ADR-0004** — decision stands; fix the framing. Partial spend is `payment.budget`, not our
   extension. Decide whether our balance keys off a `payment.budget` constraint in the mandate
   (interoperable) or an out-of-band ceiling (not).
4. **ADR-0002** — add a known-exception paragraph for the Checkout JWT: either ES256 there, or
   Ed25519 plus an explicit entropy salt, which `security_and_privacy_considerations.md:143-148`
   permits.
5. **`PRD.md` FR-11.3** — this is now a much better section than it was. We can say precisely: we
   implement AP2 v0.2 open/closed mandates, `cnf` key binding, `payment.budget` and
   `payment.amount_range` constraints, and the Mandate Receipt error codes; we extend AP2 with agent
   identity and reputation, which `implementation_considerations.md:101-104` explicitly leaves to the
   commerce-protocol layer.
6. **ADR-0006** — consider adopting `invalid_credential` / `unresolved_constraint` / `invalid_mandate`
   / `mandates_not_supported` into the closed `reason_code` enum alongside our own codes.
7. **Anywhere we mention installing AP2** — never `pip install ap2`. That is a third-party MIT mirror
   of the old version.
