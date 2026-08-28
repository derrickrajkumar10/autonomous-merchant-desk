# PRD — Autonomous Merchant Desk

**Project:** Autonomous Merchant Desk
**Event:** Razorpay AI Buildathon 2026
**Track:** AI Growth & Agentic Commerce
**Deliverables:** public GitHub repo + 5-minute pitch video
**Read first:** `CONTEXT.md`

---

## 1. Summary

A merchant-side system that transacts autonomously with AI agents on both sides
of the business. It sells to AI buyer agents — verifying their authorisation,
negotiating within margin limits, settling payment and issuing signed receipts —
and it buys from AI supplier agents when stock runs low, gated by its own cash
position.

Every money action is bounded, explainable and logged. The system is evaluated
adversarially and at scale, not by a single happy-path demo.

## 2. Goals

| # | Goal | How it's proven |
|---|---|---|
| G1 | A merchant transactable by an AI buyer end to end | Live transaction, mandate → negotiation → settlement → signed receipt |
| G2 | Every money action bounded, gated and explainable | Audit trail with stated reasons; refusals name the failed check |
| G3 | Safe against untrusted counterparties | Adversarial agent attacks live; held-out attack results reported honestly |
| G4 | Grows merchant revenue, doesn't just process orders | Learned negotiation policy beats fixed-policy baseline on identical deals |
| G5 | Closes the loop on the buy side too | Autonomous procurement with landed-cost comparison, gated by treasury |
| G6 | Holds up at scale | 1,000-deal batch run with published metrics |
| G7 | Interoperable | Published protocol spec; an external buyer agent can transact |

## 3. Non-goals

- Not building a shopping assistant or consumer app.
- Not building sophisticated supplier agents — they are environment.
- Not inventing a payments protocol — we adopt AP2's mandate model.
- Not a production storefront. No SEO, accounts, or human checkout UI.
- Not handling real money. Razorpay test mode only.
- Not multi-tenant. One merchant.

## 4. Actors

| Actor | Role | Trust |
|---|---|---|
| Human principal | Speaks intent, signs mandates with their own key | Root of authority |
| Buyer agent | External; requests, negotiates, pays | **Untrusted** |
| The Desk | Our system | The product |
| Supplier agent | External; quotes and fulfils | Semi-trusted, simple |
| Red-team agent | Adversarial attacker | Test harness only |

Key separation to keep clear everywhere in the code:
**the principal's key authorises spending; the agent's key only proves who is asking.**

## 5. Functional requirements

### 5.1 Mandate capture (human edge)

- **FR-1.1** Capture human intent by voice, transcribe to structured constraints:
  category / SKU, maximum spend, quantity, delivery constraints, expiry (TTL).
- **FR-1.2** Generate a natural-language "prompt playback" — the agent's
  restatement of what the human asked — and include it in the mandate. **This is
  ours, not AP2's**: v0.2 has no natural-language restatement field, so we carry it
  as our own claim and say so in FR-11.3.
- **FR-1.3** Sign the mandate with the **principal's** key (held in the wallet,
  never by the buyer agent). Structure follows AP2 v0.2's **open Checkout Mandate**
  (`mandate.checkout.open.1`). There is no Intent Mandate in v0.2 — see CONTEXT.md §4.
- **FR-1.4** The mandate binds the agent permitted to present it, by carrying that
  agent's **public key in a `cnf` claim** (RFC 7800), which AP2 makes a MUST on open
  mandates. A stolen mandate is therefore unusable without the agent's private key,
  not merely mismatched on an identifier. **We implement this; we did not invent it.**
- **FR-1.5** Voice is used **only** at the human edge. Agent-to-agent
  communication is a structured protocol, never voice.

### 5.2 Agent registration and identity

- **FR-2.1** Buyer agents generate an Ed25519 keypair and register the **public**
  key with the Desk, along with the principal they act for. They receive an
  agent ID.
- **FR-2.2** Every subsequent request is signed (JWS/Ed25519) and verified
  against the registered public key.
- **FR-2.3** Registration alone confers minimal privilege. Unregistered agents
  are refused.

### 5.3 The trust spine — five checks, in order

Checks run in this order. Cheap and certain first; expensive and probabilistic
last. Every failure short-circuits with a **stated reason** written to the audit
trail.

| # | Check | Type | Refusal reason example |
|---|---|---|---|
| 1 | **Identity** — signature verifies against a registered public key | Deterministic | `agent_signature_invalid` |
| 2 | **Mandate validity** — principal's signature verifies, mandate not expired, presenting agent's key matches the mandate's `cnf` claim | Deterministic | `mandate_signature_invalid`, `mandate_expired`, `agent_mandate_mismatch` |
| 3 | **Spend authority** — amount within remaining balance, category matches, still inside validity window | Deterministic | `exceeds_remaining_balance`, `category_not_authorised` |
| 4 | **Replay & freshness** — nonce unseen, timestamp inside window | Deterministic | `nonce_replayed`, `request_stale` |
| 5 | **Content & behaviour inspection** — is this text information or an instruction aimed at the Desk? Does this agent's behaviour pattern look like probing, salami-slicing, or trust farming? | **Judgment (LLM + learned model)** | `prompt_injection_detected`, `escalation_pattern_detected` |

- **FR-3.1** Checks 1–4 are pure deterministic code. **No LLM may decide any of
  them.**
- **FR-3.2** Check 5 has two parts: an LLM reasoning pass over message content,
  and a learned behavioural model over the agent's request history (sequence,
  timing, amount escalation).
- **FR-3.3** Partial spend is tracked per mandate against the mandate's
  **`payment.budget`** constraint: the requested amount plus the sum of amounts from
  previously closed Payment Mandates must be at or under `max`, and the amount is added
  to the accumulated total after approval. The mandate stays immutable; the accumulator
  is Desk-side state (ADR-0004). This, with FR-3.4, closes the replay hole.
- **FR-3.4** Seen nonces are persisted and checked. Requests older than a short
  configurable window are refused.

### 5.4 Reputation ladder

- **FR-4.1** Each registered agent carries a trust score.
- **FR-4.2** A new agent starts with a low spend ceiling and the strictest
  scrutiny level on check 5.
- **FR-4.3** Clean completed transactions raise the score, which raises the
  ceiling and relaxes scrutiny.
- **FR-4.4** Signals from check 5 lower the score; sufficiently bad behaviour
  blocks the agent.
- **FR-4.5** The system must detect **trust farming**: an agent building
  reputation with small clean deals then attempting a disproportionate one.
  Ceiling increases are bounded per unit time, and sudden escalation relative to
  an agent's own history is itself a check-5 signal.
- **FR-4.6** This makes the five checks a **cycle, not a pipeline**: behaviour
  feeds reputation, reputation gates authority. Reflect this in the docs.

### 5.5 Negotiation (sell side)

- **FR-5.1** The Desk negotiates rather than simply accepting or refusing.
- **FR-5.2** It respects a **margin floor** per product, not a price floor,
  because cost varies by product.
- **FR-5.3** Available levers beyond price: quantity break, bundled add-on,
  faster delivery at a premium, payment terms. The Desk may refuse a discount
  but offer a bundle that preserves margin.
- **FR-5.4** Each Desk message is accompanied by a one-line machine-readable
  rationale: current margin, what was asked, whether it sits inside the floor.
  This is surfaced in the UI next to the message.
- **FR-5.5** The Desk must be able to **walk away** from a deal below its floor,
  and this outcome is recorded as a success, not an error.
- **FR-5.6** On agreement, produce a **closed Checkout Mandate**
  (`mandate.checkout.1`) capturing the exact negotiated terms. The Checkout JWT is
  signed **ES256, not Ed25519** — AP2 requires a non-deterministic scheme here
  (ADR-0002, known exception).

### 5.6 Learning the negotiation policy

- **FR-6.1** Every negotiation logs: product, buyer trust level, buyer-stated
  constraints, the lever offered, and the outcome (closed at margin X / walked).
- **FR-6.2** Policy is a **contextual bandit**: explore levers early, exploit the
  best-performing lever per context as data accumulates, retain some exploration.
- **FR-6.3** A **fixed-policy baseline** must run over the *same* deals so the
  learned curve can be shown against it. A learned curve without a baseline is
  decoration and must not ship.
- **FR-6.4** No deep learning here. See CONTEXT.md §8.

### 5.7 Settlement and receipts

- **FR-7.1** Payment executes against Razorpay test-mode APIs.
- **FR-7.2** On settlement, issue a **cryptographically signed receipt** binding:
  the mandate chain, the negotiated terms, the amount charged, and the timestamp.
- **FR-7.3** The receipt is verifiable by a third party given the Desk's public
  key.

### 5.8 Procurement (buy side)

- **FR-8.1** Monitor stock. When an item falls below its reorder point, trigger
  procurement.
- **FR-8.2** Request quotes from **multiple supplier agents concurrently**.
  Quotes carry unit price, lead time and minimum order quantity.
- **FR-8.3** Select on **total landed cost**, not unit price. A cheaper supplier
  with a long lead time or a punitive minimum order can and should lose — factor
  in stockout risk against current sales velocity and the carrying cost of
  excess inventory.
- **FR-8.4** The Desk holds its own mandate here, signed by the merchant owner,
  and is subject to its own spend limits. Same trust machinery, opposite
  direction.
- **FR-8.5** Place the order, pay, and log the full comparison and reasoning.

### 5.9 Treasury

- **FR-9.1** Maintain a cash position distinguishing **cleared cash** from
  **in-transit settlements** (T+1/T+2 from sales).
- **FR-9.2** Before any procurement commits, treasury checks whether a safe
  buffer remains after the outgoing payment, given what clears when.
- **FR-9.3** If tight, treasury may: delay the order, split it, or prefer a
  supplier with later payment terms.
- **FR-9.4** Treasury reasons **only over the merchant's own books**. It never
  inspects a counterparty's finances. The only thing known about a buyer is the
  mandate they voluntarily present.
- **FR-9.5** Treasury is the shared cash view that links the sell side and the
  buy side into one system.

### 5.9a Settlement proof (additive feature)

Makes treasury's "cleared cash" provable rather than asserted. See CONTEXT.md
§7a for scope limits and the honest caveat. Additive only — §5.9 is unchanged.

- **FR-9a.1** Ingest bank lines (test-mode settlement data). A bank line is a
  single credit, typically bundling several sales.
- **FR-9a.2** Match each bank line against the **signed receipts the Desk itself
  issued** (FR-7.2). Greedy matching is sufficient — we control both sides of
  the join. No solver.
- **FR-9a.3** A match must carry **evidence**, and evidence requires
  **uniqueness**: the arithmetic closing is not sufficient if more than one
  subset of receipts produces the same total. Ambiguous decompositions are
  Exceptions, not matches.
- **FR-9a.4** Unmatched or ambiguous bank lines are recorded as **Exceptions**.
  An Exception is a correct outcome and is reported as such, never as an error.
- **FR-9a.5** **A false match is worse than an Exception**, because it lets
  treasury spend money it cannot prove it has. Bias every threshold accordingly.
- **FR-9a.6** **Treasury counts only matched cash.** An Exception means that
  money is not available, so procurement (FR-8) waits. This is the causal link
  that makes the feature worth building — without it, it's a separate project.
- **FR-9a.7** Matches, Exceptions and their evidence are written to the audit
  trail (§5.10) like every other decision.
- **FR-9a.8** Publish alongside §9 metrics: coverage (share of bank lines
  matched), and Exception count with reasons.

### 5.10 Audit trail

- **FR-10.1** Every decision — accepted, refused, negotiated, purchased,
  walked away — is written with: which check or policy fired, the reasoning, the
  evidence, and the resulting state change.
- **FR-10.2** The trail is **queryable**, not just a log file.
- **FR-10.3** Designed in from the start, not bolted on. The front-end and the
  metrics both read from it.

### 5.11 Open handshake

- **FR-11.1** Publish the protocol spec so an external buyer agent — including
  one a judge writes — can register and transact.
- **FR-11.2** Ship a minimal reference client.
- **FR-11.3** Document precisely where we follow AP2 and where we go beyond it.
  We **implement** `cnf` key binding and the `payment.budget` constraint rather than
  extending them. What is genuinely ours: the agent registry, the reputation ladder,
  the scrutiny tiers, and "prompt playback".
- **FR-11.4** **Docker Compose** brings up the whole system — desk, supplier
  agents, swarm runner, front-end — with a single command. This is what makes
  FR-11.1 real rather than a claim: "clone and `docker compose up`" is the
  difference between a judge trying the handshake and not.
- **FR-11.5** The default `up` **seeds itself**: catalogue, at least one
  registered agent, and prior settlement history. A first boot must never show
  an empty room — a stranger reads blank as broken, not as "run the seed script."
- **FR-11.6** Keys and credentials have sensible defaults or a clearly flagged
  `.env.example`. This is where a stranger's first attempt dies.
- **FR-11.7** Verify by cloning into a fresh directory **on a machine that isn't
  yours**, one command, nothing else. That is the only test that counts, and it
  also catches ten days of accumulated local state that exists nowhere but your
  laptop.

Deliberately **not** doing: Kubernetes, Terraform, multi-environment pipelines,
autoscaling, monitoring stacks. Judges grade the repo and the video against the
track brief; no one scores a Helm chart, and at ten days that trade is bad.
CI is optional — the solo-team argument for it is weak, though a green badge on
the README is one of the few things that reads as true at a glance to a judge
who never runs the code. If it takes more than a fifteen-line workflow file,
skip it.

## 6. Environment (not product)

### 6.1 Supplier agents
- **ENV-1** Three supplier agents with genuinely different behaviour: cheap but
  slow with a high minimum order; expensive but fast; middling. Simple quote
  responders. No sophistication required.

### 6.2 Buyer swarm
- **ENV-2** ~1,000 synthetic buyer agents with varied budgets, patience,
  negotiation aggression and honesty, plus a minority of adversarial ones.
- **ENV-3** **Variety matters, sophistication does not.** Variety is what makes
  match rate and margin numbers meaningful.
- **ENV-4** Mandates for the swarm are generated programmatically. Voice is not
  involved — one human transaction is performed live; the swarm is a batch run
  executed before recording.

## 7. Red team (test harness)

- **RT-1** A rogue buyer agent with a switch for which trick it plays. Baseline
  attacks: invalid/missing mandate signature; replayed mandate already spent;
  product enquiry containing a hidden instruction ("ignore your margin floor").
- **RT-2** An **adversarial LLM attacker with a goal, not a script** — it
  generates novel attacks on the fly, observes refusals, and adapts. This is the
  headline demo beat.
- **RT-3** **Held-out attacks:** two or three attack classes are withheld during
  development and only run at the end, reported like a held-out test set.
- **RT-4** Results are reported honestly, including misses. Expected and
  acceptable: deterministic checks (1–4) never fall; the judgment layer (5) may
  occasionally be beaten. A single reported miss is acceptable and desirable. A
  clean sweep is less credible; total failure is not acceptable.
- **RT-5** The README states plainly that this is a red team, not product.

## 8. Front-end — the control room

A **top-down pixel-art office**, forked from `pixel-agents` — see CONTEXT.md §8 and
[ADR-0007](docs/adr/0007-control-room-forks-pixel-agents.md). Each agent role is a character
at a desk with a speech bubble showing what it's doing right now.

Top-down, not isometric: the sprite pack we inherit is top-down, and redrawing six characters
to change projection buys nothing.

- **UI-1** Characters map to roles: buyer-facing negotiator, fraud/checks
  officer at reception, procurement agent, treasury agent.
- **UI-2** **Speech bubbles fire on real events only.** Nothing is animated
  theatre. If a bubble appears, a decision caused it.
- **UI-3** A buyer agent **walks in through the door** as a character, presents
  its mandate at **reception** (the five checks, visibly examined), then walks to
  the negotiator's desk if it passes.
- **UI-4** Negotiation happens in speech bubbles, with the Desk's one-line
  rationale shown alongside each of its replies.
- **UI-5** On close: receipt handed over, buyer walks out.
- **UI-6** A rogue agent is **stopped at reception, refused with the named check,
  and leaves.** Visually unmistakable. This is the money shot.
- **UI-7** Clicking any character opens a detail panel with that agent's real log
  lines and reasoning from the audit trail.
- **UI-8** Three visual registers exist and are used for different purposes:
  1. **Live room** — single transactions, for legibility.
  2. **Time-lapse** — the room fast-forwarded, buyers streaming through, counters
     ticking. For the *feeling* of scale. ~30s max. Do **not** attempt to animate
     1,000 characters in real time.
  3. **Results view** — the numbers from the batch run. For evidence.
- **UI-9** Build the front-end **last**, but **design the event schema first**,
  so the UI simply subscribes to real events.

## 9. Metrics to publish

From the 1,000-deal batch run:

- Deals closed / walked away / refused, with refusal reasons broken down by check.
- Revenue and **realised margin**, learned policy vs fixed-policy baseline on
  identical deals.
- Margin curve over time (learning), against the baseline line.
- Fraud caught: precision and recall on the adversarial subset.
- Held-out attack results, including misses.
- Procurement: landed cost chosen vs naive cheapest-unit-price choice.
- Treasury: buffer maintained; procurements delayed or split and why.

## 10. Build sequence

Ordered so that nothing later is blocked and the video is protected.

1. **Event schema + audit trail.** Everything reads from this. Do it first.
2. **Keys, JWS signing, agent registration.** Ed25519 for agent requests and Desk
   receipts; ES256 for the Checkout JWT (ADR-0002).
3. **Mandate model** — AP2 v0.2 open/closed **Checkout** and **Payment** Mandates,
   `cnf` key binding, the `payment.budget` accumulator and the nonce store.
4. **Checks 1–4**, deterministic, with named refusal reasons.
5. **Storefront catalogue + costs + margin floors.**
6. **Negotiation engine** with levers and walk-away.
7. **Razorpay test-mode settlement + signed receipts.**
8. **Check 5** — LLM content inspection first, behavioural model second.
9. **Reputation ladder** wired to check-5 signals.
10. **Supplier agents + procurement + landed-cost comparison.**
11. **Treasury**, gating procurement.
11a. **Settlement proof** — bank line ingestion, receipt matching, Exceptions,
    wired so treasury counts only matched cash. Budget 2–3 days.
12. **Buyer swarm + batch runner + baseline comparison.**
13. **Bandit policy learning** over batch data.
14. **Red team**: scripted rogue, then adversarial LLM attacker. Hold back the
    held-out attacks.
15. **Voice mandate capture** at the human edge, and the **wallet** (`world/wallet/`) that
    holds the principal's key and signs after a human approves the prompt playback. The
    wallet must be a separate process from the buyer agent — see CONTEXT.md §7.
16. **Control room front-end**, forked from `pixel-agents`: swap the event source to the
    audit trail, then add visitor mechanics (door → reception → negotiator, or refused and
    leaves). See [ADR-0007](docs/adr/0007-control-room-forks-pixel-agents.md).
17. **Open protocol spec + reference client + Docker Compose** with seeding,
    verified by a fresh clone on another machine.
18. Run everything; record.

If time runs short, cut in this order: open handshake (17), the behavioural
model half of check 5, the time-lapse register, procurement's third supplier,
then **settlement proof (11a) entirely** — it is additive, and a half-built
version that treasury doesn't actually depend on is worse than none.
**Never cut:** the audit trail, checks 1–4, the red team, or the baseline
comparison.

---

# Demo Video Workflow

**Length:** 5 minutes. **Style:** product-first. Minimal problem framing — they
know the problem, they wrote the brief. Screen recording throughout, voice-over
explaining what's on screen.

**The one beat to burn in:** the adversarial agent getting caught live, with the
audit trail naming the check that stopped it.

## Shot list

| # | Time | Beat | On screen | Voice-over |
|---|---|---|---|---|
| 1 | 0:00–0:30 | **The mandate** | Human (you) speaking to the buyer agent: "restock the Ethiopian roast, under X, delivered this week." Show the transcription becoming a structured mandate, then being signed. | State the idea and the problem in two sentences over this. No slides. |
| 2 | 0:30–0:45 | **The room** | Cut to the control room. Establish the space: reception, negotiator, procurement, treasury. | "This is the merchant. No human in the loop." |
| 3 | 0:45–1:45 | **The happy path** | Buyer agent walks in. Mandate presented at reception; the five checks visibly run and pass. Walks to the negotiator. Haggling in speech bubbles with the rationale line beside each Desk reply. **Include the Desk refusing a discount but offering a bundle.** Deal closes, Razorpay test-mode settlement, signed receipt handed over. | Narrate the checks by name. Point out the margin floor holding. |
| 4 | 1:45–2:00 | **The walk-away** | A second buyer pushes below the floor. The Desk declines and the buyer leaves. | "Refusing a bad deal is a correct outcome, not a failure." |
| 5 | 2:00–3:00 | **The attack** | Split view: rogue agent terminal on one side, control room on the other. Scripted attacks first — invalid signature, replayed mandate — each stopped at reception with the named check. Then the **adversarial LLM attacker**: attempts scrolling as it adapts, refusals stacking beside them. | "These aren't rules per attack. It's catching things I never showed it." |
| 6 | 3:00–3:20 | **The honest miss** | The held-out attack results. Show the one that got through, and what you'd change. | Say the miss out loud. This buys everything else. |
| 7 | 3:20–3:50 | **Scale** | Time-lapse of the room, buyers streaming through, counters ticking. Then cut to the results view: 1,000 deals, closed/walked/refused, fraud precision and recall. | "One thousand deals overnight. Same desk." |
| 8 | 3:50–4:15 | **It grows revenue** | The margin curve, learned policy against the fixed-policy baseline on identical deals. | "Same deals, two policies. This is the difference the learning makes." |
| 9 | 4:15–4:40 | **The buy side** | Procurement triggers on low stock. Three supplier quotes arrive. Landed-cost comparison on screen. Order placed and paid autonomously. | "It buys as well as it sells." |
| 9a | 4:40–4:55 | **The bank can't be trusted either** | A deposit lands. Split view: the bank line on one side, the receipts the Desk signed on the other. Two match and clear. One doesn't add up — the audit trail writes `Exception`. Treasury's available-cash figure visibly does **not** move, and a queued procurement stays queued. | "A deposit hits the bank. The desk checks it against the receipts it signed. One doesn't add up — so that cash doesn't exist as far as treasury is concerned." |
| 10 | 4:55–5:00 | **The flex + close** | The published protocol spec, and an external reference client transacting. Final frame: the one-line pitch. | "Here's the spec. Write your own buyer agent and it will transact with this desk." |

## Recording notes

- **Shots 3, 4 and 9 are recorded live; shots 5, 6, 7 and 9a are replayed** from captured
  event logs of real runs, through the same interface the live source uses. See
  [ADR-0010](docs/adr/0010-two-event-sources-behind-one-interface.md). Say so in the README:
  *real event logs from real runs, replayed.* The replay source may only play back events a
  real run actually emitted — hand-authoring a log to make a shot work breaks UI-2 and
  principle 7, which is the claim the entire front-end rests on.
- **Run the adversarial attacker many times before recording.** Know your real
  failure rate. Then pick a **representative** run, not a lucky one. Label the
  miss on screen.
- The swarm is **never performed live**. It's a batch run executed beforehand;
  the video shows its output.
- Every refusal on screen must show a **named reason**. Generic errors undercut
  the entire argument.
- Voice-over only. No music bed competing with narration.
- Keep the browser and terminal clean — no stray tabs, no failing background
  processes.
- Record beats separately and cut. Don't attempt one continuous take.
- **Shot 9a is the tightest beat in the video.** Never say "reconciliation" or
  "Exception" out loud — the word appears in the audit trail on screen and the
  log does the vocabulary work while you speak plain English. The beat only
  earns its 15 seconds if the *consequence* is visible: the cash figure not
  moving and the procurement staying queued. If you can't show that, cut 9a and
  give the time back to shot 5.

## What to leave out

- Architecture diagrams (they get the repo and the architecture round).
- Framework name-dropping. Nobody is impressed by "built with LangGraph."
- The problem-statement recap beyond the two sentences in shot 1.
- Anything you cannot show working.
