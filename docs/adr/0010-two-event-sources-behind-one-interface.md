# The control room has two event sources behind one interface

The control room is fed either by a **live** source (the running Desk, over the WebSocket
inherited with the fork) or by a **replay** source (captured event logs from real runs). Both
sit behind the same interface, and the front-end cannot tell which is connected.

The video needs both. Shots 3, 4 and 9 — happy path, walk-away, procurement — are deterministic
enough to perform live. Shots 5, 6, 7 and 9a are not: the RT-2 attacker is designed not to do the
same thing twice, the held-out results are a fixed set of outcomes, the time-lapse is by
definition a batch run's output (ENV-4), and 9a needs a bank line landing on cue. The PRD's own
recording note — run the attacker many times, know the real failure rate, pick a *representative*
run — already describes replay in everything but name.

## Consequences

Replay is not theatre and principle 7 survives intact, but only if the logs are real. **The
replay source may only play back events that a real run actually emitted.** Hand-authoring an
event log to make a shot work would break the one principle the whole front-end rests on. The
honest framing, for the README and the panel: *these are real event logs from real runs,
replayed.*

Useful side effect: the replay source is a deterministic fixture for developing the front-end
without standing up Postgres, the Desk, and the swarm.

Do not collapse the two sources into one "simpler" live-only path later. The video depends on
replay, and the front-end's ignorance of which source is feeding it is what keeps replay honest.
