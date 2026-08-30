# Ticket 08 — Saying something other than yes or no

*Ticket 08 of the StitchAI build. The one before it taught the system what a deal is
worth. This one is where it starts to bargain.*

Read the sections in order and stop wherever you have what you need. The first three
have no jargon in them; the code is at the end.

---

## 1. The situation

Imagine a shop where the only thing the person behind the counter can say is "yes, that's
the price" or "no".

They lose money in both directions, and the second one is easy to miss. Saying yes to a
bad deal is obviously bad. But saying no to somebody who was fifty rupees away from
buying is also bad, and it doesn't feel bad, because nothing visibly went wrong. Somebody
walked out. There is no line in the accounts for a sale that didn't happen.

A real shopkeeper does something else entirely. They say: *I can't do that price for one
bag. I can do it for five.* Or: *not on its own — but take the coffee with it and I'll do
it.* Or: *if you pay today rather than at the end of the month, yes.*

Notice what's going on in each of those. The shopkeeper is not giving anything away. They
are **changing the shape of the deal** so that the price the customer wanted becomes a
price the shopkeeper can survive. Something goes in the other direction each time — more
units, a second product, cash sooner.

And sometimes the shopkeeper says no and means it, and that is not a failure either. A
shop that never turns anybody away is a shop that is losing money on somebody.

This ticket is about teaching an automated merchant to do all three: to bargain, to trade
rather than concede, and to walk away without that counting against it.

---

## 2. What it means for the answer to be automatic

The counterparty here is not a person. It is another piece of software, buying on behalf
of a person who has gone to bed. That changes two things.

**It can ask a great many times.** A human haggler gets bored. Software doesn't. So there
has to be a point at which the conversation stops, and it has to be a rule rather than a
mood.

**Nobody is watching each decision.** So each decision has to explain itself at the time,
in a form that can be read back afterwards — by the person who owns the shop, by whoever
is asking whether the machine has been sensible, and later by a program trying to learn
which moves work.

Both of those turn out to shape the design more than the bargaining does.

---

## 3. The floor, and why it is not a price

The previous ticket gave every product three numbers: what it cost, what it is asked for,
and a **margin floor** — the smallest share of a sale that is allowed to be profit.

A floor, not a price. That distinction is the reason this whole thing works, and it is
worth a moment.

Coffee is bought at 420 and sold at 899. More than half the price is profit, so there is
a lot of room to move. A laptop is bought at 61,000 and sold at 74,999 — about four fifths
of the price is already spent before anything is sold, so there is almost no room at all.
A shop with one rule about discounts — "we can do ten percent" — is wrong about at least
one of those, and probably about both.

So the Desk does not hold a rule about discounts. It holds, per product, a share of the
sale that has to be profit, and it checks every proposed deal against that. Ten percent
off coffee is fine. Ten percent off a laptop is unthinkable. Nobody had to write either of
those down.

---

## 4. Four levers, and what each of them is really doing

When the buyer's number is below the floor, the Desk has four things it can change that
are not the price. The vocabulary calls them **levers** rather than discounts on purpose:
a discount is money given away, and each of these is a *trade*.

**Take more of them.** Packing a box and getting it to a courier costs about the same
whether it holds one kilo of coffee or five. That cost is real and it does not double when
the order does — so a five-kilo order carries it once, spread thin, and a rate the Desk
could not do on one kilo becomes affordable.

**Take something else with it.** A deal is decided as one thing, not line by line. Ten
percent off a grinder does not hold on its own. Beside a bag of coffee at the usual price,
the pair does — because the coffee brings profit that the grinder's discount can spend.
The shopkeeper hasn't got softer; they are deciding about a bigger thing.

**Have it faster, and pay for the speed.** A courier who delivers by Friday sends a bigger
bill, and the buyer pays more than that bigger bill. What is left over is profit the goods
themselves never had to earn — so the goods can afford to be cheaper.

**Pay sooner.** Money that arrives in thirty days is money the shop has to do without for
thirty days, and doing without money costs something. If the buyer pays up front, that
cost disappears, and the saving is what pays for the lower price.

Each one is a genuine exchange. The buyer gets something it said it wanted; the Desk gets
back the margin that pays for it. **Nothing here is a favour**, which is why none of it can
quietly drift into losing money.

There is a fifth thing the Desk can do, and it is deliberately not on the list: it can
simply name a lower price that still clears the floor. That is not a lever, because
nothing comes back the other way. Keeping it off the list matters later — a program
learning which move to reach for must not be able to learn "always cut the price", since
cutting the price is the thing every lever exists to avoid.

---

## 5. What the buyer has to say for a lever to exist

The Desk cannot invent the buyer's circumstances. It cannot offer five kilos to somebody
who wants one, or express delivery to somebody who doesn't care when it arrives.

So each lever is unlocked by something the buyer states about itself:

| The buyer says | The Desk may offer |
|:---|:---|
| "I'd take up to five" | a quantity break |
| "I need it by Friday" | express delivery, at a premium |
| "I can pay up front" | a better price for prompt money |

Everything a buyer says is a **claim**, not a fact. It may be exaggerating to get a better
offer. That turns out not to matter, and the reason is worth seeing clearly: the floor is
tested on **the deal that actually results**. A buyer who lies about taking five kilos gets
offered five kilos at a rate that is profitable for five kilos. Lying about what you want
cannot make an unprofitable deal profitable; it can only get you an offer for something
you didn't want.

The fourth lever is the exception, and it is the interesting one. A bundle needs a second
product — and the Desk will not put anything in a bundle that the *human* did not
authorise. That list comes off the signed mandate the buyer presented at the door, not off
anything the buyer says during the conversation. Otherwise "bundle it with a laptop" would
be a way of buying a laptop nobody agreed to buy, arrived at sideways.

---

## 6. The one place the arithmetic was wrong and had to be told off

There is a rule in the code that looks like second-guessing and isn't.

The margin arithmetic will happily approve this: *a kilo of coffee for 300 rupees, if you
also buy this 75,000 rupee laptop.* The pair clears the floor with enormous room to spare.
The sum is correct.

It is also a ridiculous thing to say to somebody who asked for coffee. They were not one
small concession away from buying a laptop, and an offer built on the possibility that
they might be is a merchant who has stopped listening.

So the policy carries a rule the arithmetic does not: **a bundled companion may not be
worth more than the thing being asked for.** A bundle is an add-on to a deal, not a deal
with an add-on. Coffee beside a grinder, yes. A laptop beside coffee, no.

This is worth flagging because it is the kind of rule that gets deleted by somebody
tidying up, on the grounds that the maths already works. The maths does already work. The
maths is answering a different question.

---

## 7. Stopping

Two different things end a conversation, and they are not the same thing.

**The gap is too wide to be worth talking about.** The Desk works out the lowest price any
available arrangement could reach. If the buyer's number is more than a tenth below even
that, it stops. Not because the buyer is below the floor — everybody who needs a lever is
below the floor — but because a buyer that far out is not one concession away, and three
more rounds would arrive at the same place having spent three more rounds.

**The buyer never moves.** A counterparty can simply repeat itself for ever, and the Desk
cannot tell a stubborn attacker from a slow honest buyer. So it counts. After six
messages, it stops.

That bound is checked **after** the Desk has worked out what it would say, not before. A
buyer that finally concedes on its sixth message still closes the deal — otherwise the
round limit would be costing money rather than saving time, which is the opposite of what
it is for.

Both endings are written down the same way: `walked_away`, for the reason
`below_margin_floor`. There is no separate "timed out" outcome, because from the Desk's
side nothing different happened. Nothing closed the gap.

**A walk-away is a success.** Not a consolation — a success, counted in the same breakdown
as closed deals and never as an incident. This is not politeness. The number that gets
counted is the number that gets optimised, and a system that counted correct refusals as
failures would be teaching itself, and later teaching a learning algorithm, to close
everything.

---

## 8. Every message explains itself

Each thing the Desk says carries a small machine-readable object beside it: what was
asked, what the margin on the table is, what the floor asks for, how far apart those two
are, and which lever was offered.

**On every message, not on the interesting ones.** The temptation is to explain the
refusals — those are the ones that look like they need justifying. It is the wrong way
round. The question somebody actually has, six months later, is *why did it agree to
that*.

One consequence worth stating. The percentages in that object are rounded for a human to
read; the decision was made on exact arithmetic that never divides. Occasionally the two
disagree — a deal reads as a hair inside the floor on the rounded percentages and was
actually a rupee short. The exact gap is recorded beside them, and that is the number that
was acted on. Rounding a margin and then deciding on the rounded value is exactly how a
floor gets crossed by nobody's decision.

A walk-away's explanation is about **the deal that was refused**, not about the best deal
the Desk could have offered. That sounds obvious and it was got wrong first: reporting the
Desk's own reachable margin made every walk-away read as comfortably profitable, which is
true of a deal that never happened and is no explanation at all.

---

## 9. Watching it happen

Four conversations with one Desk, driven the way an outside buyer agent would drive them
— real keys, real signed authorisations, through the same front door. This is the output
of `tests/negotiation/test_explainer_walkthrough.py`, asserted rather than described, so
it cannot go stale without the suite noticing.

```
A buyer who can afford a kilo of coffee at 750:

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
             margin -61.0000% on 300.00 INR revenue, floor 30.0000%, short by 273.0000 INR
```

Four things to notice.

The second buyer **got the price it asked for**. It asked for 650 and it got 650 — for
five kilos instead of one. That is what a lever is: not a smaller discount, the same
discount on a different shape of deal.

The third pair is the whole ticket in two lines. The same buyer, the same product, the
same ten percent off. Alone, the Desk counters at 3324.33 — a hundred and seventy-five
rupees above what was asked, and *just* inside the floor: seven and a half paise of room.
With coffee authorised, the same ten percent is granted outright, because the pair is what
is being decided about.

The counters land on numbers nobody would choose. 3324.33 is not a shopkeeper's number.
That is deliberate — it is the least the Desk can charge, worked out and then checked, and
a rounder figure would be money left on the table in the buyer's direction.

And the walk-away reports the buyer's own deal: minus sixty-one percent margin, 273 rupees
short. Not the Desk's reachable 695.66, which would have read as a comfortable profit on a
sale that did not happen.

---

## 10. What comes out of the end

When a negotiation closes, the Desk signs a **closed Checkout Mandate** — a document
saying, in a form somebody else can check, exactly what was agreed: the items, the
quantities, the prices, the terms, and which signed authorisation it was negotiated under.

The shape is AP2's, the payments standard this project builds on. Its schema has the
*merchant* sign the terms, which is where the requirement that the Desk hold a signing key
comes from, and it deliberately leaves the contents of that document unconstrained — so
the negotiated prices and terms sit inside the standard rather than beside it.

One thing it does not contain: **cost, or margin**. The buyer holds this document, and
what the Desk paid for the goods is not the buyer's business. The handling charge is a
cost with no revenue, so the buyer never sees a line for it; express delivery appears as
the amount charged and not as what the courier took. The margin position goes to the audit
trail, which is the Desk's own.

One divergence, which [ADR-0012](../adr/0012-the-desk-signs-the-closed-checkout-mandate.md)
records in full. In AP2's autonomous mode the *buyer's* agent signs the outer envelope of
that document. Here the Desk signs both layers, because a negotiation is a conversation
rather than a form and the Desk has to be able to say what it agreed to whether or not the
counterparty comes back to counter-sign. The cost is a genuinely weaker claim, and it is
stated rather than glossed: **a closed mandate here proves what the Desk committed to. It
does not prove the buyer agreed.** The evidence for the second is the audit trail. Adding
the counter-signature is ticket 30's, and nothing here has to change for it.

---

## 11. The vocabulary, now that you need it

- **Desk** — our system. The merchant that sells to machines.
- **Margin floor** — the least share of a sale that may be profit. A share, and
  deliberately **never a price**: `price floor` and `minimum price` are banned words in
  this repository (`CONTEXT.md` §6).
- **Lever** — a non-price move: quantity break, bundle, delivery speed, payment terms.
  Four of them, and the set is closed.
- **Charge** — a part of a deal that is not a product. Handling, express delivery.
  Introduced in ticket 07 and used here.
- **Terms** — how fast it arrives and when it is paid for. Standard and on-delivery unless
  something was traded for something else.
- **Ask** — what the buyer says it wants. A claim, recorded as a claim.
- **Rationale** — the object beside each Desk message: margin, floor, gap, lever.
- **Walk-away** — correctly refusing a deal beneath the floor. A success. `failure` is a
  banned word for it.
- **Closed Checkout Mandate** — the signed record of what was agreed.
- **Trust tier** — which rung of the reputation ladder a buyer is on. Recorded here,
  computed later.

---

## 12. How the price is actually found

This section is the arithmetic. Skip it if you have what you need.

The Desk has to answer: *what is the least I can charge per unit, in this arrangement, and
still clear the floor?* It is solved rather than searched for.

Write the condition out. With `p` the unit price and `q` the quantity, `k` the unit cost,
`f` the product's floor, `Rc`/`Cc`/`Fc` the companion lines' revenue, cost and floor
requirement, `H` the handling cost, `Er`/`Ec` the express premium and the courier's bill,
and `c` the rate at which waiting for the money costs:

```
(p.q + Rc + Er) - (k.q + Cc + H + Ec + c.(p.q + Rc))  >=  f.p.q + Fc
```

Collect `p`:

```
p  >=  [ Fc - Rc.(1 - c) + k.q + Cc + H + Ec - Er ] / [ q.(1 - c - f) ]
```

That is one division and it is exact. But it is not the last word, and this is the part
worth reading twice.

**The solved price is then verified.** The cost of waiting is rounded to a real amount of
money before it is charged — you cannot be out of pocket by a fraction of a paisa — so the
solved price can be a hair short of covering it. Rather than trust the algebra, the policy
rounds up to the scale the product is priced at and then asks the **same margin function
everything else asks**, stepping up until it holds.

That is the rule the whole package rests on: there is exactly one function that decides
whether a deal clears the floor, and no part of the code has a private opinion about it. A
policy with its own notion of *just inside* is how a floor gets crossed by nobody's
decision. If the two ever disagree by more than rounding could explain, the Desk raises
rather than returning a price — a defect in our own arithmetic, and not something a
counterparty can cause.

There is one number in this file a reasonable person could set differently: how far below
its own best price the Desk will keep talking. A tenth. That is a judgement about
conversations rather than about margin, and it is named and commented where it is made.

---

## 13. Where the code lives

```
desk/negotiation/lever.py       the four levers, and why the set is closed
desk/negotiation/terms.py       delivery and payment, and what each costs
desk/negotiation/ask.py         what a buyer says it wants
desk/negotiation/rationale.py   the object beside every message
desk/negotiation/policy.py      which lever, at what price, when to walk
desk/negotiation/deal.py        rounds, the trail, and the signed outcome
desk/negotiation/tier.py        the trust tier, declared but not computed
desk/mandate/closed.py          the closed Checkout Mandate
desk/identity/signing.py        the Desk's own key
world/storefront/terms.py       what express delivery actually costs here
```

The last line is the same split the catalogue made. **How a margin is computed is the
Desk's business; what a merchant charges for a courier is the world's.** Swap
`world/storefront/` for a different one and nothing defensible moves.

Two seams are deliberate. `Policy` is an interface with one method, because ticket 21
replaces the lever choice with a learned one and the fixed policy has to still run beside
it — a learned curve with no baseline next to it is decoration that must not ship
(`FR-6.3`). And the trust tier arrives as an argument rather than being looked up, because
computing it is the reputation ladder's job in ticket 12.

The fixed policy does not read the tier, which surprises people. It is on purpose: this
Desk bargains the same way with a stranger as with a regular. What reputation gates is how
much an agent may spend and how hard it is inspected, not what it is charged — and a
"fixed" baseline that quietly priced by reputation would already be doing half of what the
learned policy is supposed to discover, which would make the comparison worthless.

---

## 14. What this ticket deliberately does not do

- **It does not choose the best lever.** It reaches for the first workable one in a fixed
  order. Learning which is best over product, trust tier and stated constraints is
  ticket 21, and this policy is the control it is measured against.
- **It does not take money.** Nothing settles, nothing is charged, no receipt is issued.
  Ticket 09. The closed mandate is what that ticket charges against.
- **It does not compute the trust tier.** Ticket 12's ladder.
- **It does not model the buyer.** A reproducible, seeded definition of a counterparty —
  budget, patience, aggression, honesty — is ticket 19, and it is what makes two policies
  comparable over identical deals. Until then a buyer is whatever the tests drive.
- **It does not inspect what the buyer wrote.** Check 5, the model-backed pass that reads
  message content for instructions aimed at the Desk, is ticket 10.
- **It does not re-check authority per round.** Bargaining carries no new authority, so no
  mandate is re-presented; the authorisation was established once at the front door and is
  spent at the end.

---

## 15. If you want to read the code

Start with `desk/negotiation/__init__.py` — four ideas, and the last two are the ones that
make this more than a haggling loop. Then `policy.py` for the decision and `deal.py` for
the conversation around it.

The tests are the other way in. `tests/negotiation/test_negotiating.py` drives whole
negotiations through `TrustSpine.receive` with real keys and real signed mandates and
asserts on the audit trail — which is the same contract the control room and the published
metrics read, so a test reading it exercises the thing those two will.
`test_fixed_policy.py` is the one place that talks to the policy directly, because that is
the interface a learned policy will have to honour too.

**Counts, actually run:** 61 tests in `tests/negotiation/`, 60 in `tests/mandate/` (up 13
for the closed mandate), 58 in `tests/catalogue/` (up 8 for charges) and 43 in
`tests/identity/` (up 7 for the Desk's key). 401 in the suite as a whole, plus one skipped
— the AP2 conformance test, which needs the throwaway environment `pyproject.toml`
describes.

Two existing files changed for good reasons. `tests/spine/test_no_model_call.py` refuses
to let a new package appear under `desk/` without somebody stating whether it is part of
checks 1 to 4; `negotiation` is not, and is now listed there with the reason. It also
caught `secrets` arriving as a new import in the mandate library — salt for a disclosure,
which goes into a digest and never into a decision, so it is listed with that reason
rather than waved through.
