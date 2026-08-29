"""The worked example in ticket 07's explainer, section 7, as a test.

The explainer quotes this run's output verbatim. A script nobody runs is how a quoted
output goes quietly stale, so it is asserted here instead: change a cost, a floor or
the way a bundle's floor is blended, and this fails rather than the explainer silently
starting to lie.

Three passes over the same three products. The first asks all three for the same
discount and gets three different answers. The second finds where each one's floor
actually bites. The third is the lever -- one discount, refused alone and granted in a
bundle.

To see the output rather than assert it::

    .venv/Scripts/python.exe -m pytest tests/catalogue/test_explainer_walkthrough.py -s
"""

from __future__ import annotations

from decimal import Decimal

from desk.catalogue import Line, Margin, Offer, Product, margin_on
from tests.catalogue.conftest import COFFEE, GRINDER, PRODUCTS


def _at(product: Product, discount: Decimal | str, quantity: int = 1) -> Margin:
    return margin_on(
        Offer.of(Line(product=product, quantity=quantity, unit_price=product.discounted(discount)))
    )


def _most_it_will_take(product: Product) -> int:
    """The largest whole-percent discount this product's floor still allows."""
    allowed = [
        percent for percent in range(100) if _at(product, Decimal(percent) / 100).inside_floor
    ]
    return max(allowed)


def _bundle() -> Margin:
    return margin_on(
        Offer.of(
            Line(product=GRINDER, quantity=1, unit_price=GRINDER.discounted("0.10")),
            Line(product=COFFEE, quantity=1, unit_price=COFFEE.list_price),
        )
    )


def test_the_explainers_worked_example() -> None:
    lines: list[str] = []

    lines.append("Fifteen percent off, asked of each of the three:")
    lines.append("")
    for product in PRODUCTS:
        margin = _at(product, "0.15")
        lines.append(f"  {product.sku:<17} {margin!s}")

    lines.append("")
    lines.append("The most each will take before its own floor bites:")
    lines.append("")
    for product in PRODUCTS:
        lines.append(
            f"  {product.sku:<17} cost {product.cost.amount:>9}"
            f"   floor {product.margin_floor * 100:>5}%"
            f"   takes {_most_it_will_take(product):>2}% off"
        )

    lines.append("")
    lines.append("Ten percent off the grinder, alone and then beside coffee at list:")
    lines.append("")
    lines.append(f"  alone     {_at(GRINDER, '0.10')!s}")
    lines.append(f"  bundled   {_bundle()!s}")

    report = "\n".join(lines)
    print("\n" + report)

    assert report == EXPECTED


#: What the explainer quotes. Regenerate with the ``-s`` invocation in the docstring.
EXPECTED = """\
Fifteen percent off, asked of each of the three:

  SKU-COFFEE-1KG    margin 45.0370% on 764.15 INR revenue, floor 30.0000%, inside by 114.9050 INR
  SKU-GRINDER-BURR  margin 19.3047% on 2974.15 INR revenue, floor 25.0000%, short by 169.3875 INR
  SKU-LAPTOP-14     margin 4.3124% on 63749.15 INR revenue, floor 15.0000%, short by 6813.2225 INR

The most each will take before its own floor bites:

  SKU-COFFEE-1KG    cost    420.00   floor 30.00%   takes 33% off
  SKU-GRINDER-BURR  cost   2400.00   floor 25.00%   takes  8% off
  SKU-LAPTOP-14     cost  61000.00   floor 15.00%   takes  4% off

Ten percent off the grinder, alone and then beside coffee at list:

  alone     margin 23.7877% on 3149.10 INR revenue, floor 25.0000%, short by 38.1750 INR
  bundled   margin 30.3377% on 4048.10 INR revenue, floor 26.1104%, inside by 171.1250 INR"""
