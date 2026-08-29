# Ticket 05 — Replay and freshness, and the two clocks

*Fifth in the series. [Check 3 and the spend ceiling](ticket-04-spend-authority.md) came
before it, and this one assumes nothing from it beyond a sentence of recap.*

The three checks before this one read a request very carefully and none of them asks
what time it is. This is the one that does, and it turns out to need two clocks rather
than one.

---

## 1. The situation

Imagine you write a cheque, hand it to someone, and they photocopy it on the way to the
bank. Everything on the copy is real. Your signature is real, the amount is real, the
date is real. The bank has no way to look at the piece of paper and say *this is not a
cheque* — because it is one. What the bank has to know instead is something the paper
cannot tell it: **have I already cashed this?**

That is the entire problem here, and it is not a problem about forgery. A machine
listening to the conversation between a shopper's assistant and a shop can copy the
message that says *buy the coffee* and send it again. Nothing in the copy is false.
Everything in it was true when it was said. Sending it a second time is not lying; it is
repeating, and repeating is enough to buy the coffee twice.

There is a quieter version of the same problem. Suppose the copy is not sent again a
second later but a week later. Is it still fair for the shop to act on it? The person
who said *buy the coffee* said it on Tuesday. It is now next Tuesday. Nothing has
changed about the message. Quite a lot has changed about the world.

So a shop that only ever asks *is this message genuine* will be robbed by a tape
recorder. It has to also ask *is this happening now*.

## 2. What we built, in plain words

Two things, and they fit together in one sentence: **the shop remembers what it has
already done, and it insists that what it is being asked to do was asked just now.**

The remembering is a list. Every time the shop honours a handover, it writes down a
one-off value that came with it, and refuses to honour that value ever again. The value
is called a **nonce** — a number used once — and it does the same job as the little
serial number on the cheque.

The insisting is a clock. Every handover comes stamped with the moment it was made, and
the shop refuses anything stamped more than a short while ago. That is a **freshness
window**, and it is why a recording of today's traffic is worthless tomorrow.

The list lives in the database rather than in memory, because "the shop was restarted"
is not a reason a replay should work. And the window is a setting rather than a number
in the source, because two minutes is our guess and somebody running this for real will
want their own.

## 3. The one thing that is not obvious

Here is the part that took the longest to get right, and it is worth understanding
before any of the vocabulary.

The person's authorisation and the assistant's handover are **two different pieces of
paper, signed by two different people, at two different moments.** The person signs
*"you may spend up to two thousand rupees on coffee, and this expires in an hour"* —
once, in advance. The assistant signs *"I am handing this to you, now"* — every single
time it walks up to the counter.

Once you see that they are two pieces of paper, you can see that checking only one of
them leaves a hole, and that the two holes are different shapes:

- **Check only the authorisation.** Then a recording works, because the authorisation is
  just as valid on the copy as on the original. This is the hole the whole ticket is
  about.
- **Check only the handover.** Then an assistant can walk up with a very fresh, very
  genuine *"I am handing this to you, now"* attached to an authorisation that ran out
  last week. The handover is impeccable. What it is handing over is expired.

There is a third case that only appears once you have both, and it is the one that
convinced us the pairing was real: a handover dated **before** the authorisation it is
handing over. That is not a clock being slightly wrong. It is a proof that was made
before there was anything to prove.

So the check reads both, and asks the question neither one can ask of itself: *does the
handover sit inside the life of the thing being handed over?*

## 4. The vocabulary, now that you need it

Everything above is real. Here are the names for it.

The person is a **principal**. The assistant is a **buyer agent**. The shop is the
**Desk**. The person's signed authorisation is a **mandate** — you met it in
[ticket 03](ticket-03-mandate-library.md).

The assistant's *"I am handing this to you, now"* is a **key-binding JWT**. Take that
apart: a **JWT** is a small blob of claims with a signature over them. **Key binding**
is the idea that the mandate names one specific assistant's key — the mandate says
*"only the holder of this key may present me"* — so a signature by that key, over this
handover, is the assistant proving it really is the one named. It is a **proof of
possession**: not proof of who you are, but proof that you have the thing.

Four claims inside it do the work:

| Claim | Reading | What it stops |
|:---|:---|:---|
| `nonce` | a number used once | the same handover twice |
| `aud` | who this was handed to | a proof made for a different shop |
| `iat` | when it was made | a recording of last week |
| `sd_hash` | a fingerprint of *what* was handed over | the proof being peeled off and stuck to something else |

The last one is the least obvious and the most load-bearing. Without it, an assistant
could make one perfectly honest proof and then attach it to a different mandate — a
signature over nothing in particular is a signature that fits anything.

And the format: a mandate travels as an **SD-JWT**, which is the signed part followed by
its **disclosures** (the individual claims, carried alongside), separated by tildes. The
proof of possession is appended after the last tilde:

```
<signed mandate>~<disclosure>~              handed over with no proof
<signed mandate>~<disclosure>~<proof>       handed over with one
```

Whether the string ends in a tilde is the whole rule for telling a proof from a
disclosure. It is a positional rule, which is what makes it safe to apply before
anything has been verified.

## 5. What check 4 actually does

Six questions, in order. Five are answered from the bytes in front of it; the sixth
reads the database, which is exactly why it is last.

1. **Is there a proof of possession, and does it verify?** Against the key the mandate
   names, over this exact presentation, stamped as the right kind of artefact.
2. **Was it made for us?** `aud`. A proof addressed to another shop is a real signature
   by the right key that we were simply never given.
3. **Was it made recently?** `iat`, inside the window.
4. **Was it made after the person authorised?** The handover's clock against the
   mandate's `iat`.
5. **Was it made while the authorisation was still alive?** The handover's clock against
   the mandate's `exp`.
6. **Have we honoured this nonce before?**

If all six pass, the nonce is spent — written to the store, in the same database
transaction as the audit entry explaining why. It cannot come back, even if a later
check refuses this request for some other reason. That is correct: a retry is a new
request and deserves a new proof.

Two refusal reasons, and every refusal is one of them. `nonce_replayed` is question six
alone. Everything else is `request_stale`, which reads as *the Desk could not establish
that this is current and meant for it*. That folding is deliberate and follows
[check 1](ticket-02-agent-identity.md), where an unregistered key and a forged signature
both come back as one answer: the counterparty gets one sentence, and the audit trail
gets the specific one.

## 6. Where the nonce comes from — and the honest caveat

In the specification we are following, the **verifier** issues the nonce. The shop hands
the assistant a fresh challenge, the assistant signs it back, and the shop knows the
proof cannot predate the challenge.

We do not do that, because there is nothing to do it over yet — the Desk has no
request-and-response boundary until ticket 30 builds one. So the assistant chooses its
own nonce and the Desk refuses a repeat.

**What that costs, stated plainly.** A verifier-issued challenge proves a proof is
*newer than the challenge*. An agent-chosen nonce proves only that it is *different from
the last one*. The gap between those two is covered by the freshness window and nothing
else — which is why the window has to be short, and why weakening it weakens more than
it looks like it does. When ticket 30 gives us a boundary, the challenge belongs there,
and the nonce store underneath it does not change.

There is a second, smaller consequence of the same choice. Because the assistant picks
the value, the store is keyed by *(agent, nonce)* and not by nonce alone. A single
global list would let one agent burn a value another was about to use, just by guessing
it. Scoping costs nothing: a proof captured from a different agent is signed by that
agent's key, and check 2 refuses it against the mandate's named key long before check 4
reads a nonce out of it.

## 7. Seeing it for yourself

Real output from
[`tests/freshness/test_explainer_walkthrough.py`](../../tests/freshness/test_explainer_walkthrough.py),
which wires up the real thing against a real Postgres — enrol a principal, register an
agent, sign one mandate — and then hands that one mandate over six times.

It is a **test**, not a script, and that is deliberate: it asserts every line below, so
if check 4's behaviour ever changes this page stops being true *and the suite goes red*.

```
.venv/Scripts/python.exe -m pytest tests/freshness/test_explainer_walkthrough.py -s
```

```
One mandate, handed over six times:
  as signed, just now                      -> check 2 passed, honoured
  the identical bytes, again               -> check 2 passed, refused: nonce_replayed
  same mandate, a fresh proof              -> check 2 passed, honoured
  a proof made an hour ago                 -> check 2 passed, refused: request_stale
  a proof made for another shop            -> check 2 passed, refused: request_stale
  a fresh proof, other mandate             -> check 2 passed, refused: request_stale

The mandate itself, after all six:
  still verifies at check 2:     True
  same mandate_id as before:     True
  handed over with no proof:     refused: request_stale
```

Every line says *check 2 passed* first. That is not padding — it is the argument. The
mandate is genuine on all six handovers, so nothing about reading the mandate more
carefully could have separated them.

Now read lines two and three together. The identical bytes that worked a moment ago are
refused; then the **same mandate**, under a freshly signed proof, works again. The
credential was never the thing being spent. The handover was.

And the last line: a mandate with no proof attached at all is refused. Checks 1 to 3 are
perfectly happy with that shape, which is precisely why check 4 will not treat the proof
as optional.

## 8. The decisions that cost something

**The proof is signed Ed25519, and the specification's own examples say ES256.** We did
not get to choose. A proof of possession proves possession of *the key the mandate
names*, and our agent keys are Ed25519 because an agent's identity is its key's
fingerprint ([ADR-0011](../adr/0011-agent-identity-is-the-key-thumbprint.md)) and giving
agents a second key would give them a second identity. The cost is real: Google's own
helper for building these proofs cannot build ours, and a verifier that accepted only
ES256 proofs could not read one. It is not a *new* cost — that verifier could not have
read our mandate's key binding either — but it is a cost, and
[ADR-0002](../adr/0002-jws-ed25519-for-all-signing.md) is where the ledger of it is
kept.

**Passing check 4 spends the nonce, even if a later check refuses the request.** The
alternative — spend it only once the whole spine passes — sounds friendlier and is
wrong. It would mean a request that was refused for its *content* could be sent again
byte for byte, which hands an attacker unlimited attempts at the one check that is
allowed to be uncertain.

**A refusal on freshness does not spend the nonce.** The mirror of the above, and it
goes the other way for a reason: an agent whose clock is wrong has not replayed
anything, and burning a value it had already put on the wire would leave it unable to
retry with the value it has.

**We trim the nonce store, and the horizon is not a caller's to choose.** An
append-only list of every handover ever grows without bound. It is safe to forget a
nonce *only* once the window would refuse its presentation anyway — so the trimming
horizon is computed from the window rather than passed in. Set them independently and
someone will eventually set retention shorter than the window, which reopens the hole
silently. What forgetting still allows is an agent reusing an old nonce on a *new*
proof; that is a fresh signature over a fresh timestamp, which is a new request rather
than a replayed one, and it buys the agent nothing an unused value would not.

**The clock-skew allowance widens the window at both ends.** A counterparty clock
running slow makes an honest proof look old; one running fast makes it look
future-dated. Neither is a replay. The cost is that the effective window is the
configured one plus the skew, in both directions, and the trail records both numbers so
nobody has to guess which was in force.

## 9. Proving it, rather than asserting it

Every acceptance criterion on the ticket has a test named after it. The interesting ones
are the ones that are not the criteria:

- **Eight concurrent claims of one nonce produce exactly one winner.** Run for real
  against Postgres, with threads. A store that read *unseen* and then wrote would let
  two copies of one recording through under load — the replay hole in miniature — so
  claiming is a single `INSERT ... ON CONFLICT` and the primary key is the arbiter.
- **A restart does not forget.** A second connection pool over the same database is what
  a restarted process gets, and the nonce is still spent.
- **The same hop, two deployments, two verdicts.** Ninety seconds old: stale to a Desk
  configured for sixty, current to one configured for an hour, with no code between
  them.
- **A proof lifted onto another mandate is refused.** Both mandates are the same
  principal's and both name the same agent, so every other check passes on the pair.
  Only `sd_hash` knows which one the agent was actually holding.
- **The digest that names a mandate does not move when a proof is attached.** If it did,
  an agent would get a fresh spend ceiling for every presentation.
- **A `iat` of `true` is malformed rather than ancient.** `bool` is an `int` in Python,
  so an unguarded reader turns it into 1970 and refuses the request as stale — a true
  verdict reached for a false reason, with a sentence in the trail saying the agent's
  clock was wrong when it was not.
- **A claim the Desk would have to keep is bounded, and the database says so too.** A
  nonce is stored for ever and every claim lands in a hash-chained entry, so an
  unbounded one is unbounded growth in two permanent places — available to anyone who
  has registered a key, which costs nothing.
- **A setting left blank stops the Desk.** Read as *unset*, an empty
  `STITCHAI_DESK_AUDIENCE` would quietly restore the shipped name and refuse every
  honest agent that had been told the real one, under a refusal reason about freshness:
  a true sentence about entirely the wrong thing.

### Counts actually seen

Run on 2026-08-29 against Python 3.11.9 and an embedded Postgres:

| Environment | Result |
|:---|:---|
| Project venv, no SDK | **222 passed, 1 skipped** |
| Throwaway venv with the SDK | **227 passed** |

Thirty-seven of those are new here: fourteen on check 4, eleven on reading a proof of
possession, seven on the policy, five on the nonce store — plus the walkthrough above. The
skip is the conformance module, which skips at import when the SDK is absent and says
how to build the environment that runs it; those five tests still pass unchanged, which
is the thing worth knowing, since this ticket changed how mandates are parsed.
`ruff check`, `ruff format --check` and `mypy --strict` are clean across all 70 files.

## 10. What this ticket deliberately does not do

| Left out | Who owns it |
|:---|:---|
| A verifier-issued nonce challenge | Ticket 30, which builds the protocol boundary to issue one over |
| Running the four checks in order, and short-circuiting | Ticket 06 |
| AP2 delegation chains — several hops joined by `~~` | Not owned; recognised and refused with a sentence |
| The closed mandate (`kb+sd-jwt`) — a specific negotiated deal | Ticket 08 |
| `payment.agent_recurrence` — how *often* a mandate may be reused | Not owned; needs a rate over the history this check now records |
| Content inspection of a fresh request | Ticket 10 (check 5) |

One deserves a sentence. **A delegation chain is a different artefact to a proof of
possession**, even though both are key-binding JWTs and both sit after a tilde. A chain
is an assistant handing authority on to another assistant, and following one means
verifying each hop against the previous hop's named key. The Desk reads a root mandate
and the one hop presenting it. A chain is refused with a sentence saying so, rather than
mis-parsed into a refusal about something else.

## 11. The code

| File | What it is |
|:---|:---|
| [desk/freshness/check.py](../../desk/freshness/check.py) | check 4 — the six questions, and the only part that writes to the trail |
| [desk/freshness/key_binding.py](../../desk/freshness/key_binding.py) | reading one proof of possession: `nonce`, `aud`, `iat`, `sd_hash` |
| [desk/freshness/nonces.py](../../desk/freshness/nonces.py) | the store, and why claiming is one statement |
| [desk/freshness/schema.py](../../desk/freshness/schema.py) | one table, and the primary key that *is* the uniqueness rule |
| [desk/freshness/policy.py](../../desk/freshness/policy.py) | the window, the skew and the audience, read from the environment |
| [desk/mandate/sdjwt.py](../../desk/mandate/sdjwt.py) | `split_presentation` and `sd_hash_of` — telling a proof from a disclosure |
| [world/agents/keys.py](../../world/agents/keys.py) | the agent's side: `present`, which signs the proof |

The terse contract, for someone writing code against it, is
[docs/freshness.md](../freshness.md).

### Using it

```python
from desk.freshness import FreshnessCheck, NonceStore, install_schema

with pool.connection() as conn:
    install_schema(conn)

# The agent's side: this mandate, handed to this Desk, now.
presented = agent.present(mandate, audience="stitchai-desk")

# The Desk's side. Check 2 first, always — check 4 reads what check 2 verified.
verified = mandate_check.verify(presented, presented_by=identity)
outcome = FreshnessCheck(NonceStore(pool), trail).evaluate(verified, presented_by=identity)
if outcome.passed:
    ...        # the nonce is spent; these exact bytes will never be honoured again
```

Configuration, for a merchant who wants a different window:

```
STITCHAI_FRESHNESS_WINDOW_SECONDS=120
STITCHAI_CLOCK_SKEW_SECONDS=30
STITCHAI_DESK_AUDIENCE=stitchai-desk
```

A value that is set but unreadable stops the Desk rather than quietly reverting to the
default. Someone who widened the window and got 120 seconds anyway would believe a
setting that is not in force, and would only find out from a refusal they could not
explain.

## 12. Glossary

| Term | Meaning |
|:---|:---|
| **Nonce** | A value used once. The Desk refuses to honour the same one from the same agent twice. |
| **Key-binding JWT** | The agent's signature over *this handover of this mandate, now*. A proof of possession, not a proof of identity. |
| **Proof of possession** | Evidence that you hold a particular key, as opposed to evidence of who you are. |
| **`sd_hash`** | The fingerprint of the presentation a proof was made over, which is what stops it being moved to another one. |
| **Freshness window** | How old a proof may be before the Desk stops honouring it. |
| **Clock skew** | How far a counterparty's clock may disagree with ours before an honest agent starts being refused. |
| **Audience (`aud`)** | The name a proof is addressed to. A proof made for another verifier is not ours. |
| **Disclosure** | One part of a signed mandate, carried beside the signature. The tilde rule is how a disclosure is told from a proof. |

## 13. Next

**Ticket 06 — the spine.** Four checks now exist and nothing runs them in order. That
ticket makes the ordering explicit and the short-circuit provable: a refusal at position
N leaves no trail entry for any check after N, and each of the nine refusal reasons is
reachable through the protocol boundary. It is also where the reason-code count in §5
stops being a design argument and starts being a test.
