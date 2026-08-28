# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root, or
- **`CONTEXT-MAP.md`** at the repo root if it exists: it points at one `CONTEXT.md` per context. Read each one relevant to the topic.
- **`docs/adr/`**: read ADRs that touch the area you're about to work in. In multi-context repos, also check `src/<context>/docs/adr/` for context-scoped decisions.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## File structure

Single-context repo (most repos):

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-event-sourced-orders.md
│   └── 0002-postgres-for-write-model.md
└── src/
```

Multi-context repo (presence of `CONTEXT-MAP.md` at the root):

```
/
├── CONTEXT-MAP.md
├── docs/adr/                          ← system-wide decisions
└── src/
    ├── ordering/
    │   ├── CONTEXT.md
    │   └── docs/adr/                  ← context-specific decisions
    └── billing/
        ├── CONTEXT.md
        └── docs/adr/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders), but worth reopening because…_

---

## This repo specifically

`CONTEXT.md` here is a **background document**, not a bare glossary. Read all of it, but
note that its authoritative parts for vocabulary and decisions are:

- **§6 Vocabulary** — the glossary. It carries an **Avoid** column, and those words are
  banned in identifiers, log lines, docs and narration. `Exception` is never an *error*;
  a `Walk-away` is never a *failure*; a `Margin floor` is never a *price floor*; a `Match`
  is never *reconciliation*. Violating this is a review finding, not a style nit.
- **§5 Design principles** — these settle arguments. Cite them by number.
- **§8 Stack decisions** — one-line pointers into `docs/adr/`, where the trade-offs live.

`PRD.md` is the spec. `CONTEXT.md` explains why the spec is shaped the way it is; read it
first, as both files instruct.

New terms go in §6 with an Avoid entry. New hard-to-reverse decisions go in `docs/adr/`
with a pointer added to §8.
