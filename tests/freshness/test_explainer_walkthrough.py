"""The worked example in ticket 05's explainer, section 7, as a test.

The explainer quotes this scenario's output verbatim. A script nobody runs is how a
quoted output goes quietly stale, so it is asserted here instead: if check 4's behaviour
ever changes, this fails rather than the explainer silently starting to lie.

One mandate, presented six times. The point the output is meant to make is that the
*mandate* is never used up and the *presentation* always is -- so an agent that keeps
signing fresh proofs keeps transacting, and an agent replaying a recording gets exactly
one hit, the one that was recorded.

To see the output rather than assert it::

    .venv/Scripts/python.exe -m pytest tests/freshness/test_explainer_walkthrough.py -s
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from desk.audit import ReasonCode
from desk.freshness import FreshnessCheck
from desk.identity import AgentIdentity
from desk.mandate import MandateCheck, signed_digest_of
from tests.freshness.conftest import DESK
from tests.mandate.conftest import a_mandate
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair


@dataclass(frozen=True)
class Handed:
    """What one presentation came back with."""

    honoured: bool
    reason_code: ReasonCode | None


def _hand_over(
    freshness_check: FreshnessCheck,
    mandate_check: MandateCheck,
    identity: AgentIdentity,
    presentation: str,
    label: str,
) -> Handed:
    """Check 2 then check 4 on one presentation, printed the way the explainer shows it.

    Check 2 runs first every time. Every presentation here carries the same validly
    signed mandate, so it passes every time -- which is the whole reason check 4 has to
    exist and is worth seeing rather than being told.
    """
    verified = mandate_check.verify(presentation, presented_by=identity)
    assert verified.passed, verified.entry.payload["reasoning"]

    outcome = freshness_check.evaluate(verified, presented_by=identity)
    verdict = "honoured" if outcome.passed else f"refused: {outcome.reason_code}"
    print(f"  {label:<40} -> check 2 passed, {verdict}")
    return Handed(honoured=outcome.passed, reason_code=outcome.reason_code)


def test_the_walkthrough_in_the_explainer_still_does_what_it_says(
    freshness_check: FreshnessCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """Six handovers of one mandate: which are honoured, and which are not.

    Read the second and third lines together. The identical bytes that worked a moment
    ago are refused, and then the *same mandate* under a fresh proof works again. The
    credential was never the thing being spent.
    """
    now = int(time.time())
    mandate = a_mandate(wallet, agent)
    another = a_mandate(wallet, agent)
    recorded = agent.present(mandate, audience=DESK, nonce="nonce-recorded", issued_at=now)

    print("\nOne mandate, handed over six times:")
    first = _hand_over(freshness_check, mandate_check, identity, recorded, "as signed, just now")
    replayed = _hand_over(
        freshness_check, mandate_check, identity, recorded, "the identical bytes, again"
    )
    renewed = _hand_over(
        freshness_check,
        mandate_check,
        identity,
        agent.present(mandate, audience=DESK, issued_at=now),
        "same mandate, a fresh proof",
    )
    stale = _hand_over(
        freshness_check,
        mandate_check,
        identity,
        agent.present(mandate, audience=DESK, issued_at=now - 3600),
        "a proof made an hour ago",
    )
    elsewhere = _hand_over(
        freshness_check,
        mandate_check,
        identity,
        agent.present(mandate, audience="some-other-merchant", issued_at=now),
        "a proof made for another shop",
    )
    lifted = _hand_over(
        freshness_check,
        mandate_check,
        identity,
        another + agent.present(mandate, audience=DESK, issued_at=now).rpartition("~")[2],
        "a fresh proof, other mandate",
    )

    assert first.honoured
    assert replayed.reason_code is ReasonCode.NONCE_REPLAYED
    assert renewed.honoured
    assert stale.reason_code is ReasonCode.REQUEST_STALE
    assert elsewhere.reason_code is ReasonCode.REQUEST_STALE
    assert lifted.reason_code is ReasonCode.REQUEST_STALE

    print("\nThe mandate itself, after all six:")
    bare = mandate_check.verify(mandate, presented_by=identity)
    unchanged = bare.mandate_id == signed_digest_of(mandate)
    on_its_own = freshness_check.evaluate(bare, presented_by=identity).reason_code
    print(f"  still verifies at check 2:     {bare.passed}")
    print(f"  same mandate_id as before:     {unchanged}")
    print(f"  handed over with no proof:     refused: {on_its_own}")

    assert bare.passed and unchanged
    assert on_its_own is ReasonCode.REQUEST_STALE
