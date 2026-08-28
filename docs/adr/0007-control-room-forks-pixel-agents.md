# The control room is a fork of pixel-agents, not a bespoke renderer

The control room (PRD §8) forks [pixel-agents-hq/pixel-agents](https://github.com/pixel-agents-hq/pixel-agents)
(MIT). It supplies the renderer, sprites, walking and pathfinding, seats and areas, speech
bubbles, the layout editor, and a local server with a WebSocket feed — a week of work we do
not have a reason to redo, on a project whose contribution is the merchant, not the pixels.

We replace the event source and add one new mechanic:

- **Event source.** Its `HookProvider` seam exists for swapping in another *coding* tool
  (Codex, Gemini); we are swapping in another *event vocabulary*. Our provider reads the
  audit trail (ADR-0006) rather than Claude Code hooks.
- **Visitors.** Upstream models one agent, one character, one persistent seat. UI-3 and UI-6
  need a transient character that enters at a door, is screened at reception, and either
  walks on to the negotiator or is refused and leaves. That is new behaviour, not an adapter.

The four Desk roles — checks officer at reception, negotiator, procurement, treasury — are
permanent seated characters.

## Consequences

The front-end is TypeScript while the rest of the system is Python; the seam is the WebSocket
feed, and it is the only place the two meet.

PRD §8 said *isometric*; the sprite pack is top-down and we are not redrawing six characters
to change projection. The PRD has been corrected rather than left promising something we
will not ship.

Attribution is not optional. The MIT notice, the upstream project, and the
[JIK-A-4 Metro City](https://jik-a-4.itch.io/metrocity-free-topdown-character-pack) character
pack are credited in the README. A project whose entire thesis is provenance does not quietly
strip a licence.
