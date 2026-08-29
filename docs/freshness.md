# Replay and freshness (check 4)

The contract for `desk/freshness/`. For *why* it is shaped this way, read
[the ticket 05 explainer](explainers/ticket-05-replay-and-freshness.md).

Checks 1 to 3 ask three questions about a request and none of them is *when*. A recording
of a request that passed all three passes all three again, for as long as the mandate
lives. Check 4 is what makes a request happen once.

---

## Two layers

AP2 puts the two halves of "now" in two places, and check 4 reads both
([the research note](research/ap2-mandate-model.md), section 3):

| Layer | Claims | Signed by | Per |
|:--|:--|:--|:--|
| Mandate | `iat`, `exp` | the principal | authorisation |
| Key-binding hop | `nonce`, `aud`, `iat`, `sd_hash` | the agent | presentation |

Neither alone closes the hole. A fresh hop over a lapsed mandate is an agent proving,
very recently, that it holds authority it no longer has. A stale hop over a live mandate
is a recording.

### The hop on the wire

RFC 9901 appends it after the last separator, so a presentation *without* key binding is
the one that ends in `~`:

```
<issuer JWS>~<disclosure>~            no key binding
<issuer JWS>~<disclosure>~<KB-JWT>    key binding
```

`sd_hash` is the digest of everything up to and including that last `~` — the signed
part **and** the disclosures — which is what stops a hop being lifted onto a different
presentation. Note this is not the digest that names a *mandate*: `digest_of` is taken
over the issuer JWS alone so that it does not move when disclosures are reordered, and
`sd_hash_of` is taken over the presentation because binding to the exact bytes is its
whole job.

The hop is signed **EdDSA**, not ES256. The key it proves possession of is whichever key
the mandate's `cnf` endorses, and ours are Ed25519 agent keys (ADR-0011) — so this is
[ADR-0002](adr/0002-jws-ed25519-for-all-signing.md)'s known exception seen from the other
side rather than a new one. `typ` is RFC 9901's `kb+jwt`. AP2's `kb+sd-jwt` is a
delegation hop or a closed mandate and is refused here.

---

## The six questions, in order

Five are answered from the presentation in front of the Desk; one reads state, which is
why it is last.

1. **Is there a hop, and does it verify?** Against the key check 2 proved the mandate
   endorses, over this exact presentation, signed as a `kb+jwt`.
2. **Was it addressed to us?** `aud` against the configured audience.
3. **Was it made recently?** The hop's `iat`, inside the window.
4. **Was it made after the human authorised?** Hop `iat` against mandate `iat`.
5. **Was it made while the authorisation was live?** Hop `iat` against mandate `exp`.
   Distinct from check 2, which compares `exp` to *now*.
6. **Has this nonce been spent?** The only question that touches the database.

Passing spends the nonce, and the row and the trail entry commit together. The
presentation cannot be made again even if check 5 goes on to refuse it — a retry is a
new request and needs a new proof.

## Refusals

Two reason codes, and every refusal is one of them.

| Reason | When |
|:--|:--|
| `nonce_replayed` | Question 6 alone: this agent has presented this nonce before. |
| `request_stale` | Everything else — no hop, an unreadable or unverifiable hop, a hop for another audience, a hop outside the window, a hop outside the mandate's life. |

`request_stale` reads as *the Desk could not establish that this request is current and
meant for it*. Folding the structural refusals into it follows check 1, where an
unregistered key and a forged signature are both `agent_signature_invalid`: the wire gets
one answer and the trail gets the sentence that tells them apart. It is also what ticket
06 requires — nine reachable refusal reasons across checks 1 to 4.

---

## Configuration

Three settings, read from the environment at construction (FR-3.4). A value that is set
but unreadable raises `Misconfigured` naming the variable, rather than falling back to
the default: an operator who widened the window and got the default anyway would believe
a setting that is not in force.

| Variable | Default | Meaning |
|:--|:--|:--|
| `STITCHAI_FRESHNESS_WINDOW_SECONDS` | `120` | How old a hop may be. |
| `STITCHAI_CLOCK_SKEW_SECONDS` | `30` | How far a counterparty clock may disagree. Widens the window at **both** ends. |
| `STITCHAI_DESK_AUDIENCE` | `stitchai-desk` | The name a hop's `aud` must carry. |

Taking a default is spelled *unset*. A variable set to an empty value raises too, because
nobody exports a blank window and means 120 seconds.

AP2 is silent on all three — on nonce length, on retention, and on any skew allowance —
so these are ours, correctly so.

## The nonce store

One row per presentation honoured, in `seen_nonce`.

- **The primary key is the uniqueness rule.** Claiming is one
  `INSERT ... ON CONFLICT DO NOTHING`, so concurrent copies of one captured presentation
  are settled by the index. A read-then-write would be the replay hole in miniature.
- **Keyed by `(agent_id, nonce)`**, not by nonce alone. Nonces are the holder's to choose
  until the Desk issues challenges, so a global key would let one agent burn a value
  another was about to use. Scoping costs nothing: a hop captured from another agent is
  signed by that agent's key and is refused by check 2's `cnf` binding first.
- **Bounded.** `nonce` and `aud` are refused past `MAX_CLAIM_CHARS` (256) and the column
  carries the same ceiling as a `CHECK`. Both are stored and both go into hash-chained
  trail entries, so without a bound a registered agent could grow two permanent things
  at will.
- **Persisted, so a restart is not a way to make a replay work.**
- **Trimmed by `forget_spent_nonces`**, to the same instant the window enforces and no
  further. A forgotten nonce cannot replay its presentation, because that presentation is
  refused as stale before any nonce is read. Trimming to a shorter horizon than the window
  would reopen the hole, which is why the horizon is the policy's and not a caller's.

---

## Using it

```python
from desk.audit import AuditTrail
from desk.freshness import FreshnessCheck, NonceStore, install_schema

with pool.connection() as conn:
    install_schema(conn)

check = FreshnessCheck(NonceStore(pool), trail)     # policy from the environment
outcome = check.evaluate(checkout_outcome, presented_by=identity)
if outcome.passed:
    ...                       # the nonce is spent; this presentation is now used up
```

`evaluate` takes check 2's outcome, not a mandate string — it needs the presentation that
verified and the key that was proven. Handed a refused outcome it raises, because a
refusal is an answer already.

**One presentation, not both mandates.** `sd_hash` binds a hop to exactly one, so a
buyer agent presenting an open Checkout Mandate and an open Payment Mandate signs a hop
for each and gets a verdict for each. Running the spine over both, in order, is ticket 06.

The agent side is `AgentKeypair.present`:

```python
presented = agent.present(mandate, audience="stitchai-desk")   # fresh nonce, iat now
```

---

## In the trail

Every outcome, pass or refusal, writes one entry under `check_4_replay_freshness_passed`
or `check_4_replay_freshness_refused`. The evidence carries both layers' instants **and
the policy the decision was made under**, so a refusal read back next month says what the
window was at the time rather than what it is now:

```json
{
  "check": 4,
  "reasoning": "the agent proved it holds its key over this exact presentation, ...",
  "evidence": {
    "window_seconds": 120,
    "clock_skew_seconds": 30,
    "audience": "stitchai-desk",
    "nonce": "3sJ0m-nMLQ7hK1xQd9pQvA",
    "key_binding_issued_at": "2026-08-29T14:22:04+00:00",
    "binds_presentation": "kZ9...",
    "mandate_issued_at": "2026-08-29T14:22:04+00:00",
    "mandate_expires_at": "2026-08-29T15:22:04+00:00",
    "presented_at": "2026-08-29T14:22:04+00:00"
  },
  "state_change": {"nonce": "spent", "request": "fresh"}
}
```

The nonce is recorded deliberately: it is spent the moment it is honoured, so writing it
down costs nothing, and it is the whole of the evidence behind a `nonce_replayed` refusal.

---

## What this is not

- **Not a verifier-issued challenge.** AP2 assumes the *verifier* supplies the nonce.
  The Desk has no request/response boundary to issue one over yet, so the holder chooses
  it and the Desk refuses a repeat. The cost is stated in the explainer; ticket 30 owns
  the boundary where a challenge would live.
- **Not delegation.** An AP2 chain joined by `~~` is recognised and refused with a
  sentence saying the Desk reads a root mandate and one hop.
- **Not the closed mandate.** A `kb+sd-jwt` is a negotiated deal; the negotiation ticket
  owns it.
- **Not `payment.agent_recurrence`.** How *often* a mandate may be reused is a rate over
  the presentation history this check now records, and it is not evaluated here.
- **Not content inspection.** Whether the text inside a fresh request is safe is check 5.
