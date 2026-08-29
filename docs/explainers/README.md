# Explainers

One file per completed ticket, written to be read in order and to be read by someone who
does not already know the answer.

Each one starts with no jargon at all and adds detail in layers, so you can stop at the
section where you have what you need. They are the *why* and the *how it fits together*;
the terse contract docs beside them (`docs/audit-trail.md`, `docs/agent-identity.md`,
`docs/mandates.md`) are the *what*, for someone already writing code against it.

| Ticket | Explainer | In one line |
|:---|:---|:---|
| 01 | [The audit trail](ticket-01-audit-trail.md) | A permanent record of every decision that nobody, including us, can quietly change. |
| 02 | [Agent registration and identity](ticket-02-agent-identity.md) | An agent introduces itself once, then proves every message is really from it. |
| 03 | [Mandates and check 2](ticket-03-mandate-library.md) | The human's signed authorisation, made useless to anyone but the agent it names. |

## Writing one

See the house rules in `CLAUDE.md`. In short: plain English first, technical detail
last, every claim true of the code as it actually stands, and every snippet actually
run before it goes in.
