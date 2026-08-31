"""The worked example in ticket 09's explainer, as a test.

The explainer quotes this run's output verbatim. A script nobody runs is how a quoted
output goes quietly stale, so it is asserted here instead: change what a receipt binds,
what the trail records, or when the accumulator moves, and this fails rather than the
explainer silently starting to lie.

Two settlements of the same shape and one difference between them. A charge the rail
took, which produces a receipt and draws the ceiling down. A charge the rail declined,
which produces neither. Everything printed comes from the artefact or the trail -- never
from a row in our own tables -- because those are the two things a reader of the
explainer could check for themselves.

To see the output rather than assert it::

    .venv/Scripts/python.exe -m pytest tests/settlement/test_explainer_walkthrough.py -s
"""

from __future__ import annotations

import json

from jwcrypto.jwk import JWK
from jwcrypto.jws import JWS
from psycopg_pool import ConnectionPool

from desk.audit import AuditTrail
from desk.identity import AgentIdentity, DeskKeyVault
from desk.negotiation import Desk
from desk.settlement import Settled, Settlement
from desk.spend import BudgetAccumulator, Money
from desk.spine import TrustSpine
from tests.settlement.conftest import Agreed, StubRail, closed_deal, declined, settle
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair


def _outcome(settled: Settled, deal: Agreed, accumulator: BudgetAccumulator) -> str:
    """One settlement, as the three facts that must never come apart."""
    spent = accumulator.spent_against(deal.payment)
    # Not the receipt's id: it is a digest of the deal, which differs every run because
    # a mandate carries a nonce and a fresh salt per disclosure. What is stable, and what
    # the explainer is about, is whether one exists at all.
    receipt = "none" if settled.receipt is None else "issued, naming the closed deal"
    return (
        f"  rail       {settled.charge.status}\n"
        f"  receipt    {receipt}\n"
        f"  drawn down {spent.spent} of {spent.ceiling}"
    )


def test_the_explainers_worked_example(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    rail: StubRail,
    trail: AuditTrail,
    vault: DeskKeyVault,
    pool: ConnectionPool,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    accumulator = BudgetAccumulator(pool)
    lines: list[str] = []

    lines.append("Two kilos of coffee at 750, and a rail that takes the money:")
    lines.append("")
    taken = closed_deal(spine, selling, wallet, agent, identity, quantity=2)
    settled = settle(settlement, taken, identity)
    lines.append(_outcome(settled, taken, accumulator))

    lines.append("")
    lines.append("What a stranger reads out of that receipt, with jwcrypto and the")
    lines.append("published key, and none of our code:")
    lines.append("")
    assert settled.receipt is not None
    jws = JWS()
    jws.deserialize(settled.receipt.signed)
    jws.verify(JWK(**vault.published().receipt.jwk()))
    claims = json.loads(jws.payload)
    lines.append(f"  signature  verifies under {jws.jose_header['alg']}")
    lines.append(f"  agreed     {claims['agreed']['total']} {claims['agreed']['currency']}")
    lines.append(f"  terms      {json.dumps(claims['agreed']['terms'], sort_keys=True)}")
    lines.append(f"  charged    {claims['charged']['amount']} {claims['charged']['currency']}")
    lines.append(f"  rail       {claims['rail']['rail']} {claims['rail']['charge_id']}")
    lines.append(f"  chain      {', '.join(sorted(claims['mandate_chain']))}")

    lines.append("")
    lines.append("The same deal again, against a rail that declines:")
    lines.append("")
    rail.answer = declined()
    refused = closed_deal(spine, selling, wallet, agent, identity, quantity=2)
    settle(settlement, refused, identity)
    lines.append(_outcome(Settled(rail.answer, None, None, ()), refused, accumulator))

    lines.append("")
    lines.append("What the trail says about the two of them:")
    lines.append("")
    for entry in trail.query():
        if entry.event_type.value.startswith(("settlement_", "receipt_")):
            state = entry.payload["state_change"]["settlement"]
            lines.append(f"  {entry.event_type.value:<22} {state}")

    report = "\n".join(lines)
    print("\n" + report)

    assert report == EXPECTED
    # The two ledgers are separate mandates, so the declined one is untouched while the
    # taken one is drawn down. That is the pair the explainer's last section is about.
    assert accumulator.spent_against(taken.payment).spent == Money.of("1500.00", "INR")
    assert accumulator.spent_against(refused.payment).spent == Money.of("0", "INR")


#: What the explainer quotes. Regenerate with the ``-s`` invocation in the docstring.
EXPECTED = """Two kilos of coffee at 750, and a rail that takes the money:

  rail       captured
  receipt    issued, naming the closed deal
  drawn down 1500.00 INR of 200000.0 INR

What a stranger reads out of that receipt, with jwcrypto and the
published key, and none of our code:

  signature  verifies under EdDSA
  agreed     1500.00 INR
  terms      {"delivery": "standard", "payment": "on_delivery"}
  charged    1500.00 INR
  rail       razorpay pay_TESTMODE0000001
  chain      closed_checkout, open_checkout, open_payment

The same deal again, against a rail that declines:

  rail       failed
  receipt    none
  drawn down 0 INR of 200000.0 INR

What the trail says about the two of them:

  settlement_attempted   attempted
  receipt_issued         receipt issued
  settlement_attempted   attempted
  settlement_incomplete  did not complete"""
