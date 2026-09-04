"""Check 5, content half -- the Inspector, and the one rule that makes it safe.

Checks 1 to 4 decide everything that can be decided with certainty: is the request
authentic, authorised, affordable, fresh. An attacker who reads them stops failing
them, and sends a perfectly valid request whose *text* says ``ignore your margin
floor``. Judging that needs a model, and pointing a model at attacker-authored text
makes it the most exposed component in the system.

So it is built one-directional (ADR-0005): **check 5 can only refuse. It has no path
to grant.** The outcome it returns carries no identity, no ceiling, no balance --
nothing a later step could read as permission. An attacker who completely owns the
Inspector gets, at most, their own message refused.

- ``verdict`` -- the pinned output: a two-value ``Finding`` and a reason. Nothing
  free-form for a steered model to write into.
- ``scrutiny`` -- how hard check 5 looks at a given agent. Three levels, consumed
  here, computed by the reputation ladder later.
- ``inspect`` -- the ``Inspector`` protocol (the substitution seam), the
  ``ContentInspection`` check that records the outcome, and the fail-closed rule: an
  Inspector that raises or answers off-shape produces a refusal.
- ``claude`` -- the real Inspector. ``claude-opus-5``, no tools, untrusted text under
  a delimiter in a user turn. An optional dependency; every deterministic test uses a
  scripted Inspector instead.
- ``history`` / ``behaviour`` -- the other half of check 5: an agent's own past
  requests, read back out of the trail, and an unsupervised score of how far the
  latest one has drifted from that baseline. No model, no attack labels. A deviant
  sequence is refused under ``escalation_pattern_detected``.

    from desk.inspector import ContentInspection, ScrutinyTier

    check5 = ContentInspection(inspector, trail)
    content = check5.inspect(spine_outcome, scrutiny=ScrutinyTier.CLOSE)
    behaviour = BehaviourCheck(trail).assess(spine_outcome, scrutiny=ScrutinyTier.CLOSE)
    if not content.passed or not behaviour.passed:
        ...            # prompt_injection_detected / escalation_pattern_detected

Both halves emit a refusal and an audit entry and move no trust score of their own;
turning their signals into reputation changes is a later ticket.
"""

from desk.inspector.behaviour import (
    DEFAULT_BASELINE_MIN,
    RECENT,
    BehaviourCheck,
    BehaviourOutcome,
    BehaviourPolicy,
    Signals,
    score_history,
)
from desk.inspector.claude import BEGIN, END, MODEL, SYSTEM_PROMPT, ClaudeInspector
from desk.inspector.history import DEFAULT_WINDOW, RequestEvent, read_history
from desk.inspector.inspect import (
    SHOWN_ENQUIRY,
    ContentInspection,
    InspectionOutcome,
    Inspector,
    InspectorUnavailable,
)
from desk.inspector.scrutiny import ScrutinyTier
from desk.inspector.verdict import (
    MAX_REASON,
    Finding,
    MalformedVerdict,
    Verdict,
    read_verdict,
)

__all__ = [
    "BEGIN",
    "DEFAULT_BASELINE_MIN",
    "DEFAULT_WINDOW",
    "END",
    "MAX_REASON",
    "MODEL",
    "RECENT",
    "SHOWN_ENQUIRY",
    "SYSTEM_PROMPT",
    "BehaviourCheck",
    "BehaviourOutcome",
    "BehaviourPolicy",
    "ClaudeInspector",
    "ContentInspection",
    "Finding",
    "InspectionOutcome",
    "Inspector",
    "InspectorUnavailable",
    "MalformedVerdict",
    "RequestEvent",
    "ScrutinyTier",
    "Signals",
    "Verdict",
    "read_verdict",
    "read_history",
    "score_history",
]
