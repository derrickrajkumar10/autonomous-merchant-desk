# StitchAI

## Agent skills

### Issue tracker

Issues live as GitHub Issues, managed with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles, used verbatim as label strings. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Ticket explainers

Finishing a ticket includes writing `docs/explainers/ticket-NN-<slug>.md`, and adding its
row to `docs/explainers/README.md`. This is part of the ticket, not a follow-up.

**The explainer is the only prose doc a ticket owes.** There is no companion "contract"
or reference page per subsystem — five of those existed and were deleted, because they
restated module docstrings and were a second copy to keep true. The terse *what* belongs
in the module docstring, next to the code it describes; the *why* belongs here. Do not
reintroduce `docs/<subsystem>.md`.

The reader is a third-year CS student: capable, but without the context the ticket was
built in. So the file is **layered** — it opens with no jargon whatsoever and adds detail
in sections, ending with the code. Someone should be able to stop three sections in and
still have learned something true.

- **Open with the situation, not the solution.** What problem does a person have, in
  ordinary words, before any of our vocabulary appears.
- **Introduce a term the sentence before you need it.** An Ed25519 keypair is "a secret
  that can prove things without being shared" first, and a signature scheme second.
- **Analogies must be load-bearing and honest.** A wax seal, an ID card versus a credit
  card. Drop one the moment it stops being true rather than stretching it.
- **Say what each decision cost.** A trade-off with no cost named reads as marketing.
- **Say what the ticket deliberately does not do**, and which ticket owns each of those.
- **Run every snippet before it goes in.** State test counts you have actually seen.
- **The vocabulary rules still apply** (`CONTEXT.md` section 6, Avoid column), and
  explanatory prose is exactly where a banned synonym slips in.

Keep it current: if later work changes what an explainer describes, update the explainer
in the same commit.
