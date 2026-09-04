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

    from desk.inspector import ContentInspection, ScrutinyTier

    check5 = ContentInspection(inspector, trail)
    verdict = check5.inspect(spine_outcome, scrutiny=ScrutinyTier.CLOSE)
    if not verdict.passed:
        ...            # verdict.reason_code is prompt_injection_detected

The behavioural half of check 5 -- deviation from an agent's own request history -- is
the next ticket. This one reads one message and emits one refusal.
"""

from desk.inspector.claude import BEGIN, END, MODEL, SYSTEM_PROMPT, ClaudeInspector
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
    "END",
    "MAX_REASON",
    "MODEL",
    "SHOWN_ENQUIRY",
    "SYSTEM_PROMPT",
    "ClaudeInspector",
    "ContentInspection",
    "Finding",
    "InspectionOutcome",
    "Inspector",
    "InspectorUnavailable",
    "MalformedVerdict",
    "ScrutinyTier",
    "Verdict",
    "read_verdict",
]
