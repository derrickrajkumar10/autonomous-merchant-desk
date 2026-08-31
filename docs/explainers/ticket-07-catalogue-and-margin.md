# Ticket 07 — Knowing what a deal is worth

*Seventh in the series. [The order of the questions](ticket-06-spine-ordering.md) came
before it. That one finished the part of the system that decides whether the Desk is
**allowed** to do business with whoever is asking. This is the first piece with an
opinion about whether it **should**.*

---

## 1. The situation

Somebody walks into a shop and asks for ten percent off.

Behind the counter there are two people. The first knows what everything costs the
shop. The second knows only the price on the label.

The second one can say yes or no, and that is genuinely all they can do. They cannot
say *why*, they cannot offer anything instead of the discount, and — this is the part
that costs money — they cannot tell the difference between ten percent off a bag of
coffee and ten percent off a laptop. Both are "ten percent". One of them is fine. The
other one is most of what the shop was going to make on the sale.

The first person does not have that problem, and they did not have to be clever about
it. They just know one extra number.

That is the whole of this ticket. Every product gets told what it cost, so that the
Desk can work out what a proposed deal actually earns instead of arguing about the
label price.

## 2. What we built, in plain words

Three numbers per product instead of one:

- what it **cost** the Desk to have the thing,
- what the Desk **asks** for it,
- and the **least share of a sale that has to be profit**.

That last one deserves a slow sentence, because everything else follows from it.

It is a *share*, not an amount. "At least thirty percent of whatever this sells for
has to be profit" — not "never sell this below six hundred rupees". Those sound like
the same rule and they are not, and the difference is the reason this ticket is a
ticket at all.

An amount is a rule about one product. A share is a rule that means the same thing on
every product, no matter what any of them cost. Set it once per product, and the Desk
can be asked about a price nobody has ever quoted before — a price on a bundle of
three things, at a quantity nobody listed — and it will still have an answer, and the
answer will still be the same rule.

The second half: **the Desk works this out for the whole deal at once, not for each
item in it.** Three things on the table is one sum. That sounds like a detail about
arithmetic. It is actually what makes haggling possible, and section 5 is about why.

## 3. The one thing that is not obvious

Here are three real products, and the same question asked of all of them: *will you
take fifteen percent off?*

| | Cost | Asking price | Its own floor | Fifteen percent off? |
|:---|---:|---:|---:|:---|
| Coffee, 1 kg | 420 | 899.00 | 30% | yes, comfortably |
| Burr grinder | 2,400 | 3,499.00 | 25% | no |
| 14-inch laptop | 61,000 | 74,999.00 | 15% | no, nowhere close |

Now read the third column again. **The laptop has the loosest rule of the three** — it
only has to keep fifteen percent, where the coffee has to keep thirty — and it is
still the one that cannot move. It will take four percent off and no more. The coffee,
under the strictest rule of the three, will take a third off and still be fine.

The rule is not what decides. The **cost** decides. The laptop is bought at eighty-one
percent of what it is asked for, so there was never much in the price to give away in
the first place.

This is why a single shop-wide discount policy — "we can always do ten percent" — is
not a cautious version of the right answer. It is a different answer that happens to
be correct for some of the shelf and quietly wrong for the rest of it. And it is wrong
in the expensive direction on exactly the expensive items.

**What it cost:** three numbers to maintain per product instead of one, and a cost
figure that has to be kept honest. A price you can read off a label; a cost you have to
actually know. If the cost is stale the floor is a lie, and the Desk will hold a line
that no longer exists. Procurement (ticket 14) is what eventually keeps it true; until
then a person edits a file.

## 4. Why a bundle is one deal and not three

Ask for ten percent off the grinder on its own and the Desk says no. That discount
leaves 749.10 of profit where the grinder's own floor asks for 787.28. Thirty-eight
rupees short, so the Desk walks — which the vocabulary insists is a **walk-away** and a
success, not a lost sale.

Now put a bag of coffee at full price next to it and ask for the same ten percent off
the grinder.

The Desk says yes.

Nothing about the grinder changed. What changed is what the Desk is deciding about.
The pair earns 1,228.10 between them against a combined ask of 1,056.98, so the offer
holds — the coffee is carrying the grinder, and there is enough in the coffee to carry
it.

That move is the single most valuable thing in this ticket, and it exists *only*
because the margin is computed over the whole offer. Had we built the obvious thing —
every line clears its own floor — the Desk would refuse that bundle. It would be
refusing a deal it makes money on, and it would be doing it while reporting that it was
protecting its margin.

So there is a deliberate hole in the code: the per-line breakdown that the Desk shows
you has **no verdict on it**. You can read what each line earned. You cannot ask a line
whether it is acceptable, because there is no such method to call. That question only
has a sensible answer about a whole offer, and code that could ask it of a line would
eventually be used to refuse a bundle that was perfectly fine.

**What it cost:** a bundle can hide a bad line. Somebody looking at a closed deal sees
that it held overall, and has to open the breakdown to see that one line inside it was
under water. The breakdown is kept and shown for exactly that reason — but "it held
overall" is genuinely the claim being made, and it is not the same claim as "every part
of it was fine".

And the limit, which is worth naming because it sounds like a loophole and is not:
**subsidy only runs as far as the subsidising line's actual profit.** You cannot rescue
a laptop with a bag of coffee. The coffee brings 479 rupees of profit to a hole that is
several thousand deep. Adding lines to an offer adds their costs too, so padding a bad
deal with giveaways makes it worse, not better. Both of those are tests.

## 5. Where the floor for a bundle comes from

Each line asks for its own floor times its own revenue. The offer has to earn the
total. That is the whole rule.

Two other rules were available and are worse:

- **Take the strictest line's floor.** Then a bundle is punished for containing one
  carefully-priced product, and the thirty-percent coffee would drag the whole basket
  up to thirty percent.
- **Average the percentages.** Then a line that is ninety percent of the money counts
  the same as one that is one percent of it.

Adding up what each line asks for avoids both, and it has a natural reading: the
combined floor comes out as a revenue-weighted blend of the lines' own floors. For the
grinder-and-coffee bundle that is 26.11 percent, sitting between the grinder's 25 and
the coffee's 30, and nearer the grinder because the grinder is most of the money.

## 6. A deal is not only goods

Everything so far treats a deal as a list of products. Real deals carry things that are
not products: it costs something to pack a box and get it to somebody, and it costs more
to get it there by Friday. Those amounts belong to *this* deal at *these* terms rather
than to any one product, so they ride on the offer separately, as **charges**.

A charge is a label, an amount the buyer pays, and an amount it costs the Desk. Two
shapes matter, and they are the reason two of the negotiation's levers are arithmetic
rather than assertion:

- **Cost and no revenue.** The fixed work of putting one deal out of the door. It does
  not double when the order does, so a bigger order spreads it thinner — which is what
  makes a lower rate at volume something the Desk can actually afford.
- **Revenue and cost.** Express delivery charged at a premium. The buyer pays four
  hundred, the courier takes two hundred and forty, and the hundred and sixty left over
  is margin the goods never had to find. That is how the Desk can hold a tenth off the
  grinder — the goods were not made cheaper, the deal was made bigger.

**A charge asks for no floor of its own.** A margin floor is a promise about what the
Desk earns on what it *sells*, and a courier's share is not that. So a charge hands its
profit to what the lines were already asked for and asks nothing back.

That does mean a charge can make a floor easier to clear, which would be a hole if a
counterparty could add one. None can. Charges are written by the Desk's own terms and
are never read off a request, so the only party that can put one on a deal is the party
the floor is protecting.

## 7. The vocabulary, now that you need it

- **Desk** — our system. The merchant that sells to machines.
- **Product** — one thing the Desk sells, carrying a cost, a list price and a floor.
- **Margin** — profit as a share of the sale. Sell for 899 what cost 420 and the margin
  is 479/899, about 53 percent.
- **Margin floor** — the least margin a deal may have. A share of revenue, and
  deliberately **never a price**: `price floor` and `minimum price` are banned words in
  this repo (CONTEXT.md §6), and this ticket is where the ban earns its keep.
- **Offer** — what the Desk is proposing right now: one or more **lines**, each a
  product, a quantity and a unit price. The price lives here and not on the product,
  because the price is the negotiable part.
- **Charge** — a part of a deal that is not a product: handling, express delivery. It
  carries revenue and cost and no floor of its own.
- **Lever** — a non-price concession. A bundle is one; so is a quantity break. The
  vocabulary calls them levers rather than discounts on purpose.
- **Walk-away** — refusing a deal below the floor. A correct outcome.
- **Catalogue** — the Desk's table of products. **Storefront** — the file in `world/`
  saying which products there are.

## 8. Watching it happen

Three passes over those same three products, printed by
`tests/catalogue/test_explainer_walkthrough.py`, which asserts every line below so this
section cannot quietly go stale:

```
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
  bundled   margin 30.3377% on 4048.10 INR revenue, floor 26.1104%, inside by 171.1250 INR
```

Those one-line rationales are what FR-5.4 asks for: beside every Desk reply, a
machine-readable line saying what the margin is, what was asked, and whether it sits
inside the floor. Ticket 08 puts them on the screen.

## 9. The part where nothing is allowed to round

There is one genuinely subtle thing in this ticket and it is worth the section.

Margin is a division — profit divided by revenue — and divisions do not come out
evenly. `1/3` is 0.333… forever, and a computer holding it has to stop writing digits
somewhere. So the reported margin is a rounded number. It has to be.

The temptation is then to compare that rounded number against the floor. Do not. Here
is a deal that shows why:

| | |
|:---|---:|
| Revenue | 2,000,000.00 |
| Cost | 1,333,333.00 |
| Profit | 666,667.00 |
| The floor asks for | 666,668.00 |

One rupee short. Refuse it.

But its margin is 0.3333335 exactly, and rounded to six places that is **0.333334** —
which is precisely the floor. Compare the rounded numbers and this deal passes. Compare
them and the Desk hands over a rupee it decided not to hand over, because of a rounding
rule nobody chose for this purpose.

So the decision never divides. `profit ≥ floor × revenue` says the same thing as
`profit / revenue ≥ floor`, uses multiplication instead of division, and multiplication
of two exact decimals is exact. The rounded margin still gets reported, because a human
reading a rationale line wants a percentage — but it is *only* reported. Nothing
decides on it. That case is a test
(`test_the_decision_is_made_without_dividing`), and it fails loudly if anyone ever
wires the verdict to the rounded number.

The same instinct runs through the rest of the arithmetic. Prices are exact decimals
end to end — `numeric` in Postgres, `Decimal` in Python, never a float, for the reason
[ticket 04](ticket-04-spend-authority.md) already gave about ceilings. And the one
place a rounding genuinely cannot be avoided — working out what "fifteen percent off
899.00" is in actual rupees and paise — makes two choices out loud rather than
inheriting them: it lands on the scale the list price is written at — or on whole
rupees, whichever is finer — and on a dead tie it rounds **toward the Desk**, because a
concession should be something the Desk grants deliberately and not something a
rounding rule hands over on its behalf.

That "whichever is finer" is a bug this ticket's own review caught. `Decimal` can record
a thousand as `1E+3`, meaning *one thousand, to the nearest thousand*, and rounding a
discount to that scale sent every price under 1,500 back to either the full list price
or zero. A discount silently becoming no discount is the quietest way this method could
be wrong, so the scale is clamped instead of trusted.

## 10. Where the code lives, and the split that matters

```
desk/catalogue/product.py   the three numbers, and what makes a product valid
desk/catalogue/margin.py    lines, charges, offers, and the comparison that decides
desk/catalogue/schema.py    the product table
desk/catalogue/store.py     seeding it, and reading it back
world/storefront/           which products actually exist
```

The last line is the split worth defending. **How margin is computed is the Desk's
business; which products exist is the world's.** CONTEXT.md §7 calls the storefront
catalogue environment rather than product, and this is what that means in practice:
delete `world/storefront/`, write a different one with different goods at different
costs, and the Desk works identically. Nothing defensible moved. A test asserts it, by
inventing a product no seed file mentions and pricing a deal on it.

Three things are the database's rather than the code's, in the same spirit as the audit
trail's append-only trigger and the spend ceiling's CHECK:

- a cost cannot be negative,
- a floor is a share, so it lives in `[0, 1)`,
- and **a product must be sellable at its own asking price**. A row whose list price
  already sits under its own floor describes something nobody could ever sell. That is
  a data error, not a policy, and catching it at the insert beats discovering it in the
  middle of a negotiation.

There is a trap in writing those, and the review found it. Postgres `numeric` holds
`NaN`, and it deliberately sorts `NaN` **above** every real number — so `cost >= 0` is
true of it, and a bare non-negativity check waves it straight in. It would sit in the
table until something read it back and raised, taking a whole product listing with it.
The guard that works is `cost < 'Infinity'`, false for `NaN` and for infinity both. The
guard most people reach for, `cost = cost`, does nothing here: `numeric` NaN compares
*equal* to itself, which is the opposite of the float rule everyone is remembering.

## 11. What this ticket deliberately does not do

- **It does not negotiate.** Nothing here decides what to offer, chooses a lever, or
  talks to anybody. It answers "what would this deal earn, and is that enough?" and
  stops. Ticket 08 does the negotiating; ticket 21 makes the lever choice learned.
- **It writes nothing to the audit trail.** Stocking a product is configuration, not a
  decision about a counterparty, and the trail is for the second kind (ADR-0006). The
  events that *use* these numbers — an offer made, a deal closed, a walk-away — are
  ticket 08's to record.
- **It has no method that answers "what is the least I can charge for this?"** That
  number is computable and would be convenient, and it is left out on purpose: it is a
  price floor, and naming one would put back the exact concept §6 of CONTEXT.md bans.
  A negotiator that needs it can derive it, per offer, and own the name it gives it.
- **Unit cost does not move with quantity.** Buying five hundred kilos more cheaply
  than one is real, and it is a procurement question — ticket 14, landed cost. What does
  move here is the *fixed* cost of a deal, which a charge carries and a bigger order
  spreads thinner (§6). So a quantity break is affordable for a reason the floor can
  see, rather than being a way around it.
- **There is no stock level, no supplier, no availability.** Seven columns, and the
  shortness is the guarantee.

## 12. If you want to read the code

Start with `desk/catalogue/margin.py` and read its module docstring — three ideas, and
the third is section 9 above. Then `product.py` for what makes a product valid, and
`store.py` for the two operations the table supports.

The tests are the other way in. `tests/catalogue/test_bundle.py` is the shortest
statement of what this ticket is for: the same discount, refused alone and granted in a
bundle, in one test.

**Counts, actually run:** 58 tests in `tests/catalogue/`, and 5 added to
`tests/spend/test_money.py` for the one thing `Money` was missing — a unit price times
a quantity. 457 in the suite as a whole, plus two skipped (the AP2 conformance test,
which needs the throwaway environment `pyproject.toml` describes, and ticket 09's one
Razorpay test, which skips unless test-mode credentials are set).

Eight of those 58 arrived after this ticket: `test_charge.py`, added by ticket 08 along
with §6 above, because two of its four levers are arithmetic only if a deal can carry
something that is not a product.

One existing test also changed, and it is worth a sentence because it is the good kind
of failure. `tests/spine/test_no_model_call.py` refuses to let a new package appear
under `desk/` without somebody stating whether it is part of checks 1 to 4. The
catalogue is not — it runs after the spine has finished, on a request the four checks
already accepted — so it is now listed there as deliberately outside, with that reason
written down.
