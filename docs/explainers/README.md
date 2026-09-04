# Explainers

One file per completed ticket, written to be read in order and to be read by someone who
does not already know the answer.

Each one starts with no jargon at all and adds detail in layers, so you can stop at the
section where you have what you need. They are the *why* and the *how it fits together*;
the *what* — the schemas, the exact signatures, the refusal tables — lives in the module
docstrings, which is the one copy that cannot drift from the code it describes.

| Ticket | Explainer | In one line |
|:---|:---|:---|
| 01 | [The audit trail](ticket-01-audit-trail.md) | A permanent record of every decision that nobody, including us, can quietly change. |
| 02 | [Agent registration and identity](ticket-02-agent-identity.md) | An agent introduces itself once, then proves every message is really from it. |
| 03 | [Mandates and check 2](ticket-03-mandate-library.md) | The human's signed authorisation, made useless to anyone but the agent it names. |
| 04 | [Spend authority and check 3](ticket-04-spend-authority.md) | Reading the authorisation for what it says, and a ceiling that runs down without ever being rewritten. |
| 05 | [Replay and freshness](ticket-05-replay-and-freshness.md) | A genuine message sent twice is still a robbery, so the Desk remembers what it has honoured and insists it was asked just now. |
| 06 | [The order of the questions](ticket-06-spine-ordering.md) | Cheap certain questions before expensive uncertain ones, and the first refusal ends the conversation. |
| 07 | [Knowing what a deal is worth](ticket-07-catalogue-and-margin.md) | Every product knows what it cost, so the same discount gets a different answer on coffee and on a laptop. |
| 08 | [Saying something other than yes or no](ticket-08-negotiation.md) | The Desk bargains: four levers that trade rather than concede, and a walk-away that counts as a success. |
| 09 | [Taking the money, and proving you were allowed to](ticket-09-settlement-and-receipts.md) | The charge is real, and the receipt is checkable by a stranger holding nothing but a public key. |
| 10 | [Reading a message for what it is trying to do](ticket-10-the-inspector.md) | A model reads the buyer's text for instructions aimed at the Desk — and even a fully fooled reader can only refuse, never grant. |
| 11 | [Noticing when an agent stops acting like itself](ticket-11-behavioural-score.md) | Each agent is scored against its own history, not a list of known attacks, so escalation and trust farming show up as a change of character. |
| 12 | [What an agent's record buys it](ticket-12-reputation-ladder.md) | A ladder of spending limits an agent climbs one rung at a time, where time on a rung is a cost volume cannot pay — so a clean record cannot be farmed into one big grab. |

## Writing one

See the house rules in `CLAUDE.md`. In short: plain English first, technical detail
last, every claim true of the code as it actually stands, and every snippet actually
run before it goes in.
