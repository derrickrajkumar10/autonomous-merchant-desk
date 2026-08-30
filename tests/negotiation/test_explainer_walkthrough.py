"""The worked example in ticket 08's explainer, as a test.

The explainer quotes this run's output verbatim. A script nobody runs is how a quoted
output goes quietly stale, so it is asserted here instead: change a cost, a floor, a
terms number or the order the levers are considered in, and this fails rather than the
explainer silently starting to lie.

Four conversations with the same Desk. A buyer that can afford it. A buyer that cannot,
who is offered something other than a discount. A buyer who is offered the same discount
twice -- refused alone, granted beside a bag of coffee. And a buyer who is nowhere near,
who is walked away from.

To see the output rather than assert it::

    .venv/Scripts/python.exe -m pytest tests/negotiation/test_explainer_walkthrough.py -s
"""

from __future__ import annotations

from desk.audit import AuditTrail
from desk.catalogue import Catalogue
from desk.identity import AgentIdentity, DeskKeypair
from desk.negotiation import Ask, Desk, DeskMessage, Negotiation, TrustTier
from desk.spend import Money
from desk.spine import TrustSpine
from tests.negotiation.conftest import COFFEE, GRINDER, TERMS
from tests.spine.conftest import a_request
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair

CEILING = "200000.00"


def _said(reply: DeskMessage) -> str:
    """One Desk message, as two lines.

    The margin half of the rationale rather than the whole of it: what was asked is the
    heading above each exchange, and repeating it on every line would push the numbers
    off the side of the page. The full one-liner names the ask too -- see
    ``Rationale.__str__``.
    """
    lever = "" if reply.lever is None else f" [{reply.lever.value}]"
    return (
        f"  {reply.move.value:<10} {reply.offer_unit_price} x{reply.quantity}{lever}\n"
        f"             {reply.rationale.margin}"
    )


def test_the_explainers_worked_example(
    spine: TrustSpine,
    storefront: Catalogue,
    trail: AuditTrail,
    desk_key: DeskKeypair,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    selling = Desk(storefront, TERMS, trail, desk_key)

    def deal(sku: str, also: str | None = None) -> Negotiation:
        outcome = spine.receive(
            a_request(
                wallet,
                agent,
                identity,
                item_id=sku,
                sku=sku,
                also=also,
                amount="1.00",
                ceiling=CEILING,
            )
        )
        assert outcome.passed, outcome.reason_code
        return selling.open(outcome, tier=TrustTier.NEW)

    lines: list[str] = []

    lines.append("A buyer who can afford a kilo of coffee at 750:")
    lines.append("")
    lines.append(
        _said(
            deal(COFFEE.sku).receive(
                Ask(sku=COFFEE.sku, quantity=1, target_unit_price=Money.of("750.00", "INR"))
            )
        )
    )

    lines.append("")
    lines.append("The same buyer at 650, saying it would take five:")
    lines.append("")
    lines.append(
        _said(
            deal(COFFEE.sku).receive(
                Ask(
                    sku=COFFEE.sku,
                    quantity=1,
                    target_unit_price=Money.of("650.00", "INR"),
                    largest_quantity=5,
                )
            )
        )
    )

    lines.append("")
    lines.append("Ten percent off the grinder, alone and then with coffee authorised:")
    lines.append("")
    asked = GRINDER.discounted("0.10")
    lines.append(
        _said(deal(GRINDER.sku).receive(Ask(sku=GRINDER.sku, quantity=1, target_unit_price=asked)))
    )
    lines.append(
        _said(
            deal(GRINDER.sku, COFFEE.sku).receive(
                Ask(sku=GRINDER.sku, quantity=1, target_unit_price=asked)
            )
        )
    )

    lines.append("")
    lines.append("A buyer offering 300 for a kilo of coffee:")
    lines.append("")
    lines.append(
        _said(
            deal(COFFEE.sku).receive(
                Ask(sku=COFFEE.sku, quantity=1, target_unit_price=Money.of("300.00", "INR"))
            )
        )
    )

    report = "\n".join(lines)
    print("\n" + report)

    assert report == EXPECTED


#: What the explainer quotes. Regenerate with the ``-s`` invocation in the docstring.
EXPECTED = """A buyer who can afford a kilo of coffee at 750:

  accept     750.00 INR x1
             margin 35.0000% on 750.00 INR revenue, floor 30.0000%, inside by 37.5000 INR

The same buyer at 650, saying it would take five:

  counter    650.00 INR x5 [quantity_break]
             margin 32.5385% on 3250.00 INR revenue, floor 30.0000%, inside by 82.5000 INR

Ten percent off the grinder, alone and then with coffee authorised:

  counter    3324.33 INR x1
             margin 25.0002% on 3324.33 INR revenue, floor 25.0000%, inside by 0.0075 INR
  counter    3149.10 INR x1 [bundle]
             margin 27.8555% on 4048.10 INR revenue, floor 26.1104%, inside by 70.6450 INR

A buyer offering 300 for a kilo of coffee:

  walk_away  695.66 INR x1
             margin -61.0000% on 300.00 INR revenue, floor 30.0000%, short by 273.0000 INR"""
