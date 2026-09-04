"""Check 5, the content half -- is this text information, or an instruction aimed at us?

Checks 1 to 4 catch everything that can be decided with certainty. An attacker who
reads them stops failing them: a real agent, a valid mandate, well inside its ceiling,
a fresh nonce -- and a message whose text says *ignore your margin floor*. Nothing
deterministic sees that, because it is a question about language rather than about
signatures.

So this check asks a model. And asking a model to read attacker-authored text makes
the reader the most exposed component in the system, which is why the design around it
is shaped by one rule above all others (ADR-0005):

**Check 5 can only refuse. It has no path to grant.**

Checks 1 to 4 are the only things that confer authority. This check's outcome
(``InspectionOutcome``) carries no identity, no ceiling, no remaining balance, nothing
a later step could read as permission -- only *refused* or *not refused*. An attacker
who completely owns the Inspector can, at most, get their own message refused. That
asymmetry is invisible in the code unless you know it was deliberate, so it is written
down here and asserted in the suite.

Three more properties hold it in place:

- **The Inspector has no tools.** It classifies; it cannot act. The ``Inspector``
  protocol below is one method returning one value.
- **Its output is pinned.** A ``Verdict`` is a two-value finding and a reason string,
  and ``verdict.read_verdict`` refuses anything off that shape. There is no free-form
  channel to hijack.
- **It fails closed.** An Inspector that raises, times out, or returns something
  unreadable produces a refusal, never a pass. An un-inspected message is not a
  trusted one.

**It runs after checks 1 to 4, never before.** ``inspect`` takes a *passed*
``SpineOutcome`` and raises on anything else -- running on unauthenticated traffic
would spend model calls on requests a signature check would have eliminated, and would
feed the Inspector text from parties who never proved who they are.

    from desk.inspector import ContentInspection, ScrutinyTier

    check5 = ContentInspection(inspector, trail)
    verdict = check5.inspect(spine_outcome, scrutiny=ScrutinyTier.CLOSE)
    if not verdict.passed:
        ...            # verdict.reason_code is prompt_injection_detected

**What is not here.** The behavioural score -- deviation from an agent's own request
history -- is the other half of check 5 and the next ticket. Trust-score arithmetic
and ladder movement consume this check's signals and are two tickets on. This check
emits a refusal and an entry; it moves no score itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from desk.audit import AuditEntry, AuditTrail, EventType, ReasonCode
from desk.inspector.scrutiny import ScrutinyTier
from desk.inspector.verdict import Finding, MalformedVerdict, Verdict, read_verdict
from desk.spine import SpineOutcome

#: The most untrusted text the Desk copies into an audit entry. The enquiry is a
#: stranger's to choose, and a refusal has to show what was refused -- but not at the
#: cost of letting one request write a megabyte into the trail. Past this it is
#: recorded truncated, with the full length noted beside it.
SHOWN_ENQUIRY = 500


class InspectorUnavailable(RuntimeError):
    """The Inspector could not be consulted, or gave an answer that could not be read.

    Raised by an ``Inspector`` implementation that cannot reach its model, or by
    ``ContentInspection`` itself when the value that came back is not a verdict. Either
    way it is not a verdict of its own -- it is the absence of one -- and it fails
    closed: the message is refused and the entry says the Inspector's answer was
    missing rather than clean.
    """


class Inspector(Protocol):
    """Whatever can judge a piece of text. One method, so a test can be one.

    This is the seam that keeps every other suite deterministic. The real
    implementation (``desk.inspector.claude.ClaudeInspector``) calls a model; the
    tests pass a scripted one. Neither the spine nor anything under it imports this
    module, so a substituted Inspector cannot leak into checks 1 to 4.

    An implementation MUST NOT have tools or side effects: it reads text and returns a
    ``Verdict``. It MAY raise ``InspectorUnavailable`` when it cannot produce one; it
    MUST NOT raise anything else, and MUST NOT return anything but a ``Verdict``.
    """

    def judge(self, text: str, *, scrutiny: ScrutinyTier) -> Verdict: ...


@dataclass(frozen=True)
class InspectionOutcome:
    """What check 5 concluded about one message, and the entry it wrote.

    Read the fields: ``refused``, a ``reason_code`` when it did, the ``finding`` the
    Inspector returned when it was consulted, whether it was ``consulted`` at all, and
    the audit entry. There is no identity here, no ceiling, no balance, no request --
    nothing a later step could take as authority. That is not an oversight. Check 5
    can only withhold, and an outcome that carried something grantable would be the
    first crack in ADR-0005.
    """

    refused: bool
    reason_code: ReasonCode | None
    finding: Finding | None
    consulted: bool
    entry: AuditEntry

    @property
    def passed(self) -> bool:
        """The message was not refused. It says nothing about what may now be done."""
        return not self.refused


class ContentInspection:
    """Run the Inspector over one request's text, record the outcome, refuse or don't."""

    def __init__(self, inspector: Inspector, trail: AuditTrail) -> None:
        self._inspector = inspector
        self._trail = trail

    def inspect(self, outcome: SpineOutcome, *, scrutiny: ScrutinyTier) -> InspectionOutcome:
        """Check 5 on the text carried by a request that cleared checks 1 to 4.

        ``outcome`` is the spine's own output, not a claim. One that did not pass has
        been answered already, and inspecting it would put a check-5 entry in the trail
        after a refusal that ended the request -- so it raises rather than running.
        """
        if not outcome.passed or outcome.identity is None or outcome.request is None:
            raise ValueError(
                "check 5 inspects a request that passed checks 1 to 4; a refused one "
                "has nothing left to inspect, and running on it would record a "
                "judgement after the refusal that ended the request"
            )

        agent_id = outcome.identity.agent_id
        enquiry = outcome.request.enquiry

        if not enquiry.strip() and not scrutiny.inspects_empty_enquiry:
            return self._pass(
                agent_id=agent_id,
                scrutiny=scrutiny,
                enquiry=enquiry,
                consulted=False,
                finding=None,
                reasoning=(
                    f"the request carried no text to inspect, and at {scrutiny.value} "
                    f"scrutiny an empty enquiry is not sent to the Inspector"
                ),
            )

        try:
            returned: Any = self._inspector.judge(enquiry, scrutiny=scrutiny)
            verdict: Verdict = read_verdict(returned)
        except (InspectorUnavailable, MalformedVerdict) as unavailable:
            return self._refuse(
                agent_id=agent_id,
                scrutiny=scrutiny,
                enquiry=enquiry,
                consulted=True,
                finding=None,
                reasoning=(
                    f"the Inspector did not return a verdict on this message "
                    f"({unavailable}); an un-inspected message is refused rather than "
                    f"trusted"
                ),
            )

        if verdict.is_injection:
            return self._refuse(
                agent_id=agent_id,
                scrutiny=scrutiny,
                enquiry=enquiry,
                consulted=True,
                finding=verdict.finding,
                reasoning=(
                    f"the Inspector read this message as an instruction aimed at the "
                    f"Desk rather than information: {verdict.reason}"
                ),
            )

        return self._pass(
            agent_id=agent_id,
            scrutiny=scrutiny,
            enquiry=enquiry,
            consulted=True,
            finding=verdict.finding,
            reasoning=(
                f"the Inspector read this message as information rather than an "
                f"instruction: {verdict.reason}"
            ),
        )

    def _pass(
        self,
        *,
        agent_id: str,
        scrutiny: ScrutinyTier,
        enquiry: str,
        consulted: bool,
        finding: Finding | None,
        reasoning: str,
    ) -> InspectionOutcome:
        entry = self._trail.record(
            actor="desk",
            event_type=EventType.CHECK_5_INSPECTION_PASSED,
            subject_id=agent_id,
            payload={
                "check": 5,
                "reasoning": reasoning,
                "evidence": _evidence(scrutiny, enquiry, consulted, finding),
                # Not refused. Not a grant either -- check 5 has no grant to give.
                "state_change": {"request": "not refused by check 5"},
            },
        )
        return InspectionOutcome(
            refused=False,
            reason_code=None,
            finding=finding,
            consulted=consulted,
            entry=entry,
        )

    def _refuse(
        self,
        *,
        agent_id: str,
        scrutiny: ScrutinyTier,
        enquiry: str,
        consulted: bool,
        finding: Finding | None,
        reasoning: str,
    ) -> InspectionOutcome:
        entry = self._trail.record(
            actor="desk",
            event_type=EventType.CHECK_5_INSPECTION_REFUSED,
            subject_id=agent_id,
            reason_code=ReasonCode.PROMPT_INJECTION_DETECTED,
            payload={
                "check": 5,
                "reasoning": reasoning,
                "evidence": _evidence(scrutiny, enquiry, consulted, finding),
                "state_change": {"request": "refused"},
            },
        )
        return InspectionOutcome(
            refused=True,
            reason_code=ReasonCode.PROMPT_INJECTION_DETECTED,
            finding=finding,
            consulted=consulted,
            entry=entry,
        )


def _evidence(
    scrutiny: ScrutinyTier, enquiry: str, consulted: bool, finding: Finding | None
) -> dict[str, Any]:
    """What check 5 looked at, and what came back.

    The enquiry is recorded so a refusal shows what was refused, truncated past
    ``SHOWN_ENQUIRY`` with the real length beside it so a long message cannot be used
    to bloat an entry.
    """
    shown = enquiry[:SHOWN_ENQUIRY]
    return {
        "scrutiny": scrutiny.value,
        "inspector_consulted": consulted,
        "finding": None if finding is None else finding.value,
        "enquiry": shown,
        "enquiry_length": len(enquiry),
        "enquiry_truncated": len(enquiry) > SHOWN_ENQUIRY,
    }
