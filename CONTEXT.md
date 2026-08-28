# CONTEXT.md

Background context for anyone (human or coding agent) working on this repository.
Read this before PRD.md. This file explains *why* the project is shaped the way it
is. PRD.md explains *what* to build.

---

## 1. What this is

An **autonomous merchant desk**: a system that sells to AI buyer agents and buys
from AI supplier agents, with no human in the transaction loop.

One sentence: *an autonomous merchant desk that safely sells to machines and buys
from machines, where every decision is bounded, provable, and measured at scale.*

## 2. Why it exists

AI assistants are starting to transact on behalf of people. A person says
"restock my coffee, keep it under 2,000 rupees" and their agent goes and buys it.
No human clicks checkout.

Today that breaks at the merchant. Merchant systems are built for humans with
sessions, cookies and card forms. They have no way to answer the questions that
matter when the counterparty is a machine:

- Who is this agent?
- Does a real human actually authorise this spend?
- Is this request fresh, or a replay of one I already honoured?
- Is this text a question, or an instruction aimed at me?

So the interesting problem is not the shopper. It's the merchant.

## 3. Competitive positioning

This is being built for the **Razorpay AI Buildathon 2026**, track: *AI Growth &
Agentic Commerce*. The brief asks for an agent that grows revenue for a merchant
on Razorpay test-mode APIs, or that makes a merchant transactable by an AI buyer
end to end. The brief's own bar: *every money action explainable, bounded and
gated; show the audit trail and one failure handled gracefully.*

**Assumption driving the whole design: most entrants will build a buyer agent
that shops.** We build the merchant. That is the differentiator, and every scope
decision should protect it.

## 4. Where this sits relative to existing standards

| Layer | Standard | Our relationship to it |
|---|---|---|
| Agent transport | A2A | Use it; not our contribution |
| Payment mandates | **AP2** (Google, Apache 2.0) | **Adopt its mandate model** |
| Agent identity attestation | Visa TAP | AP2 deliberately leaves this out — **we fill it** |
| Payment rails | Razorpay test-mode APIs | Use as-is |

AP2 gives us the *envelope*: how a human's authorisation is expressed, signed and
chained. It does **not** give us a merchant that decides. AP2 also binds mandates
to the **user, not the agent** — agent identity is explicitly out of scope for
AP2. That gap is where our agent-identity registry and reputation ladder live.

Standing on a standard is a strength, not a shortcut. Say so on camera.

### AP2 concepts we reuse
- **Intent Mandate** — the human's constraints: category, max price, TTL, plus
  "prompt playback" (the agent's natural-language restatement of what the human
  asked). Fits our voice capture exactly.
- **Cart / Checkout Mandate** — the specific negotiated deal.
- **Payment Mandate** — authorisation of the actual charge.
- Mandates are signed verifiable credentials carrying a timestamp, nonce and
  signer key reference — so replay and freshness checks come nearly free.
- AP2 supports an "open" / human-not-present mode, which is our delegated case.

## 5. Design principles (these settle arguments)

1. **Right tool per job.** Cryptography where certainty matters. Learned models
   where patterns matter. LLM reasoning where language matters. An LLM must
   never be the thing that decides whether a signature is valid — that's a bug,
   not innovation.
2. **Deterministic first, judgment second.** Cheap certain checks run before
   expensive probabilistic ones. Fail fast.
3. **Refuse with a stated reason.** "Rejected: mandate signature invalid" proves
   a check exists. A generic error proves nothing.
4. **General defences, not a rule per attack.** The system must catch attacks it
   was never specifically shown. This is testable and we test it.
5. **Evidence over assertion.** Every decision is logged with its reasoning and
   the evidence behind it, and is queryable afterwards.
6. **A sale is not cash until it settles.** Treasury reasons about cleared money,
   not booked revenue.
7. **The UI subscribes to real events.** Nothing in the front-end is animated
   theatre. If a speech bubble appears, a real decision caused it.
8. **Honest metrics.** Held-out attacks, reported misses, baselines next to
   learned curves. A reported failure buys more credibility than a clean sweep.

## 6. Vocabulary

Use these terms consistently in code, logs and docs. The **Avoid** column is not
decoration: those words are banned in identifiers, log lines, docs and narration. Several
of them (*error*, *failure*, *reconciliation*) actively misrepresent what the system does.

| Term | Meaning | Avoid |
|---|---|---|
| **StitchAI** | The product name. Use it in the README, the video and anything outward-facing. | Stitch, the app |
| **Desk** | The whole system — what StitchAI *is*. Sells and buys. Use this internally, in code and in logs. | Platform, service, backend |
| **Buyer agent** | External counterparty trying to purchase. Untrusted. | Customer, client, shopper |
| **Supplier agent** | External counterparty selling to us. Environment, not product. | Vendor, seller |
| **Mandate** | A signed authorisation from a human principal. | Permission, token, approval |
| **Principal** | The human whose key signs a mandate. | User, owner, account |
| **Agent identity** | The agent's own registered keypair — proves *who is asking*, not *what is authorised*. | Auth, credentials |
| **Trust score** | Per-agent reputation that gates spend ceiling and scrutiny tier. | Rating, karma |
| **Spend ceiling** | The maximum a given agent may transact for, set by its rung on the ladder. Rungs have a minimum dwell time; that dwell time is the anti-farming mechanism. | Limit, quota |
| **Scrutiny tier** | One of three discrete levels controlling how aggressively check 5 runs against an agent. | Strictness, mode |
| **Inspector** | The check-5 LLM pass. A classifier with no tools that may only refuse or lower trust, never grant. | Guard, filter, moderator |
| **Wallet** | The separate process holding the principal's key and signing mandates after a human approves the prompt playback. Never in the buyer agent's process. | Keystore, signer |
| **Margin floor** | Minimum acceptable margin on a deal. Not a price floor. | **Price floor**, minimum price |
| **Lever** | A non-price concession: bundle, quantity break, delivery speed, payment terms. | Discount, concession |
| **Walk-away** | Correctly refusing an unprofitable deal. A success, not a failure. | **Failure**, lost deal, rejection |
| **Landed cost** | Total cost of a procurement including lead time and minimum-order penalty, not unit price. | **Unit price**, cheapest |
| **Cleared cash** | Money actually settled and available. Distinct from booked revenue. | Balance, revenue |
| **Deal** | One negotiation between the Desk and one buyer agent, from mandate presented to closed or walked. | Order, transaction, session |
| **Deal spec** | The seeded, replayable definition of a buyer: product, budget, patience, aggression, honesty, seed. Two policies are compared by replaying identical deal specs, never identical transcripts. | Scenario, test case |
| **Red team** | The adversarial agent. Test infrastructure, never product. | Attacker module, security feature |
| **Swarm** | The synthetic population of buyer agents used for batch evaluation. Environment. | Load test, simulation |
| **Bank line** | A single credit landing in the merchant's bank account. Usually several sales bundled together. | Deposit, statement row |
| **Match** | A proven link from a bank line to the receipts that produced it. Must carry evidence. | **Reconciliation**, settlement |
| **Evidence** | What makes a match provable. The arithmetic closing is not enough — the decomposition must also be *unique*. | Proof, confidence |
| **Exception** | A bank line that could not be matched with evidence. A correct outcome, not a failure. | **Error**, **failure**, mismatch, unreconciled |
| **False match** | Claiming a link that isn't real. Worse than an Exception, because it lets treasury spend money it doesn't have. | False positive |

## 7. Product vs environment vs test harness

This distinction matters and should be visible in the repo layout.

- **Product** (`desk/`): the merchant desk. Everything defensible lives here.
- **Environment** (`world/`): supplier agents, the buyer swarm, the storefront
  catalogue, and the principal's **wallet** (`world/wallet/`). Deliberately simple.
  Varied, not sophisticated.
- **Test harness** (`redteam/`): the rogue agent and the adversarial attacker.
  This is a penetration-testing suite, exactly analogous to a test suite. Nobody
  should mistake it for product, and the README must say so.
- **Control room** (`controlroom/`): the forked front-end. TypeScript, reads the
  audit trail over a WebSocket. See [ADR-0007](docs/adr/0007-control-room-forks-pixel-agents.md).

The wallet sits in `world/` because it is the human-edge environment rather than the
defensible merchant — but note it is the root of authority, and it must be a **separate
process** from the buyer agent. If the principal's key ever ends up in the agent's process,
FR-1.3 and FR-1.4 become theatre and a panel will find it immediately.

## 7a. Settlement proof (the Quench merge)

This is an **additive feature**, not a change of direction. Nothing else in the
design moves.

### Why it belongs here

Treasury (FR-9) distinguishes cleared cash from in-transit settlements. Left as
it was, "cleared" is an assertion — the desk believes its bank statement. This
feature makes it provable.

The unifying idea, and the sentence worth being able to say out loud:

> **An autonomous merchant that can't be lied to by anyone — not its buyers, not
> its suppliers, not its own bank.**

The trust spine says: don't believe a counterparty without evidence. This says:
don't believe your own bank without evidence. Same epistemics, pointed inward.

### Why it's cheap here, and the honest caveat

Real reconciliation is hard because the two sides of the join are controlled by
different parties. Here they aren't: **we match bank lines against receipts the
desk itself signed** (FR-7.2). We control both sides, so greedy matching is
sufficient and no solver is needed.

**Do not oversell this as solving reconciliation generally.** If the panel asks
about the hard case — bank line to settlement where you don't control the other
side — say plainly that this is the easier version and that receipt-signing is
what makes it easy. Claiming otherwise invites a question you'd have to walk back.

### Scope: what carries over from Quench and what does not

**In:** the join concept, evidence-with-uniqueness, Exception as a first-class
correct outcome, the vocabulary above.

**Out:** CP-SAT decomposition, the six-class synthetic corpus, chargebacks,
adjustments, reserves, reversals, the close process, and the Bank Line ↔
Settlement join against a merchant ERP. That last one is the genuinely unsolved
piece and the best of the old Quench work — it does not fit this scope and
should not be forced in. Keep it for a paper or a later build.

Budget: roughly 2–3 days. If it exceeds that, cut it entirely rather than let it
eat the buy side or the red team.

## 8. Stack decisions already made

The reasoning behind these now lives in `docs/adr/`, so a future reader finds the
trade-off rather than just the outcome.

- **LangGraph** for agent orchestration — [ADR-0001](docs/adr/0001-langgraph-for-orchestration.md)
- **JSON Web Signatures over Ed25519** for all signing — [ADR-0002](docs/adr/0002-jws-ed25519-for-all-signing.md)
- **Contextual bandits** for negotiation policy, deliberately not deep learning —
  [ADR-0003](docs/adr/0003-contextual-bandits-not-deep-learning.md)
- **Python** for `desk/`, `world/` and `redteam/`; TypeScript for the control room.
- **Postgres** for the audit trail and all Desk state; **Docker Compose** for FR-11.4.
- **Razorpay test-mode APIs** for settlement.
- **Partial spend is Desk-side ledger state**, not a mutable mandate —
  [ADR-0004](docs/adr/0004-partial-spend-is-desk-side-ledger-state.md)
- **Check 5 can only refuse, never grant** —
  [ADR-0005](docs/adr/0005-check-five-can-only-refuse.md)
- **Audit trail is a hash-chained append-only table** with a closed `reason_code` enum —
  [ADR-0006](docs/adr/0006-audit-trail-is-a-hash-chained-postgres-table.md)
- **Control room forks `pixel-agents`** —
  [ADR-0007](docs/adr/0007-control-room-forks-pixel-agents.md)
- **Bank lines are synthesised; recon is never consumed** —
  [ADR-0008](docs/adr/0008-bank-lines-are-synthesised-and-recon-is-not-consumed.md)
- **Behavioural detection is unsupervised and per-agent** —
  [ADR-0009](docs/adr/0009-behavioural-detection-is-unsupervised-and-per-agent.md)
- **`claude-opus-5`** for the check-5 inspector and the RT-2 attacker, adaptive thinking,
  structured outputs. A full 1,000-deal batch costs roughly $20–30 with the system prompt
  cached, so cost does not shape this choice. A weak attacker would make the red-team
  result meaningless.

## 9. Submission constraints

- Public GitHub repo.
- 5-minute pitch video.
- Then: architecture round, then panel interview.
- Roughly a 10-day build window.

The video decides the outcome. Architecture that never reaches the screen earns
nothing. **Design backwards from the video** — but keep the system honest enough
to survive the panel round, because that's where hand-waving dies.

## 10. Known open questions

### Resolved

- **Partial spend vs AP2** — resolved. The mandate stays immutable; the balance is Desk-side
  ledger state. [ADR-0004](docs/adr/0004-partial-spend-is-desk-side-ledger-state.md).
- **Trust-score update function** — resolved in shape. Score in `[0,1]` starting at `0.1`;
  asymmetric (a clean deal adds a small increment, a check-5 signal subtracts several times
  that); ceiling is a **step ladder** with a minimum dwell time per rung rather than a
  continuous function of score, because a ladder is legible in the audit trail and on screen;
  scrutiny is three discrete tiers; score decays toward baseline on inactivity so a dormant
  high-trust agent is not a standing liability. Exact constants are tuning, not design.
- **Control room transport** — websockets. The forked front-end already ships a local server
  and WebSocket feed. [ADR-0007](docs/adr/0007-control-room-forks-pixel-agents.md).
- **Live recording vs replay** — resolved. Both, behind one interface: live for the happy path,
  walk-away and procurement; replay for the attack sequence, the honest miss, the time-lapse and
  the settlement-proof beat. Replay may only play back events a real run actually emitted.
  [ADR-0010](docs/adr/0010-two-event-sources-behind-one-interface.md).

### Still open

Nothing. Every question this file opened has been answered and recorded in `docs/adr/`.
New open questions belong here as they arise.
