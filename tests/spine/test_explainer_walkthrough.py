"""The worked example in ticket 06's explainer, section 7, as a test.

The explainer quotes this run's output verbatim. A script nobody runs is how a quoted
output goes quietly stale, so it is asserted here instead: if the spine's ordering or
any check's reason code changes, this fails rather than the explainer silently starting
to lie.

Five requests, all from one registered agent against one principal's mandates. The
first is wholly valid; each of the others is that same request with exactly one thing
wrong, and the column that matters is the last one -- which checks left an entry.

To see the output rather than assert it::

    .venv/Scripts/python.exe -m pytest tests/spine/test_explainer_walkthrough.py -s
"""

from __future__ import annotations

from dataclasses import dataclass

from desk.audit import AuditTrail
from desk.identity import AgentIdentity
from desk.spend import Money
from desk.spine import SpineOutcome, TrustSpine
from tests.spine.conftest import LAPTOP, a_request
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair


@dataclass(frozen=True)
class Sent:
    """One request's answer, in the two forms the explainer shows."""

    outcome: SpineOutcome
    line: str


def _send(spine: TrustSpine, trail: AuditTrail, request: str, label: str) -> Sent:
    """Send one request and report which checks left an entry for it.

    The checks are read back out of the trail rather than off the outcome, because the
    trail is the thing the claim is about: what a reader sees afterwards, not what the
    spine says it did.
    """
    head = trail.head()
    outcome = spine.receive(request)
    written = [
        entry.payload["check"]
        for entry in trail.query(after_seq=None if head is None else head.seq)
        if "check" in entry.payload
    ]

    stopped = outcome.refused_at
    answer = (
        "passed"
        if stopped is None
        else f"refused at check {stopped.position}: {outcome.reason_code}"
    )
    ran = " ".join(str(check) for check in written)
    line = f"  {label:<24} -> {answer:<52} (ran: {ran})"
    print(line)
    return Sent(outcome=outcome, line=line)


def test_the_walkthrough_in_the_explainer_still_does_what_it_says(
    spine: TrustSpine,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """One valid request, then four with one thing wrong each.

    Read down the last column. The refusal moves one place further along the spine each
    time, and nothing after it ever runs -- not because the later checks would have
    agreed, but because they were never asked.
    """
    valid = a_request(wallet, agent, identity)

    print("\nOne agent, one principal, one pair of mandates:")
    passed = _send(spine, trail, valid, "a valid request")
    forged = _send(
        spine,
        trail,
        a_request(wallet, agent, identity, signed_by=AgentKeypair.generate()),
        "a forged signature",
    )
    stolen = _send(
        spine,
        trail,
        a_request(wallet, agent, identity, binds=AgentKeypair.generate()),
        "somebody else's mandate",
    )
    wrong = _send(
        spine, trail, a_request(wallet, agent, identity, item_id=LAPTOP), "the wrong item"
    )
    replayed = _send(spine, trail, valid, "that first request again")

    assert passed.outcome.passed
    assert passed.outcome.remaining == Money.of("1250.00", "INR")
    assert [sent.line for sent in (passed, forged, stolen, wrong, replayed)] == [
        "  a valid request          -> passed                                               "
        "(ran: 1 2 2 3 4 4)",
        "  a forged signature       -> refused at check 1: agent_signature_invalid          "
        "(ran: 1)",
        "  somebody else's mandate  -> refused at check 2: agent_mandate_mismatch           "
        "(ran: 1 2)",
        "  the wrong item           -> refused at check 3: category_not_authorised          "
        "(ran: 1 2 2 3)",
        "  that first request again -> refused at check 4: nonce_replayed                   "
        "(ran: 1 2 2 3 4)",
    ]
    assert trail.verify().ok
