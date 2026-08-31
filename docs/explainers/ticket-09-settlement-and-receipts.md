# Ticket 09 — Taking the money, and proving you were allowed to

*Ticket 09 of the StitchAI build. The one before it taught the system to bargain and to
sign what it agreed to. This one is where the agreement becomes money, and where the
system starts producing evidence that outlives it.*

Read the sections in order and stop wherever you have what you need. The first four have
no jargon in them; the code is at the end.

---

## 1. The situation

Two people shake hands on a price. Nothing has happened yet.

The money still has to move, and — this is the part that gets underestimated — somebody
has to be able to prove afterwards *what was agreed and what was taken*. Those are two
different problems, and the second one is much harder than it looks.

Think about what "proof" normally means when you buy something. You get a paper receipt.
It has the shop's name on it, the items, the total, the date. If the shop later charges
your card twice, the receipt is what you wave at them. It works because it is a physical
object the shop handed over and cannot now take back or quietly rewrite.

Now do the same thing where the shop is a program and the buyer is a program and nobody
was awake. What is the receipt?

The obvious answer is: a row in the shop's database. And the obvious answer is worthless,
for one reason that ends the discussion — **the shop can change it.** A record you keep
about yourself is not evidence about yourself. If the buyer's owner comes back a month
later and says "you charged me ten thousand and I only agreed to fifteen hundred", a row
in our own table saying *fifteen hundred* proves nothing to them, because we are the ones
who wrote it and we are the ones being accused.

So this ticket has two jobs. Make the charge happen. And produce something that stays
true even if nobody trusts us.

---

## 2. What a signature buys you

There is a trick from cryptography that solves exactly this, and it is worth
understanding before any of our vocabulary appears.

You can hold a secret that lets you *prove things* without ever revealing the secret. You
take a document, run it through a calculation involving your secret, and get a short
string of characters out — a **signature**. Anyone in the world can then take the
document, the signature, and a *public* half of your secret that you have published, and
check that the two match.

Two things follow, and both matter here:

- **Only you could have produced it.** Nobody without the secret half can make a
  signature that checks out against your published half.
- **The document cannot be altered.** Change one character of the document and the
  signature stops matching. Not "looks suspicious" — stops matching, arithmetically.

The nearest physical thing is a wax seal on a letter, and the analogy is worth having in
your head as long as you know where it stops being true. A wax seal proves who sealed it
and shows if the letter was opened. What a wax seal *cannot* do is prove the letter's
contents were not swapped for different ones and resealed by the same person. A signature
covers the contents themselves, which is the part that matters and the part the seal
never had. So: better than a seal, and it is the "cannot be altered" half that is the
improvement.

That is the whole basis of what follows. The Desk holds a secret, signs a statement about
what it charged, and publishes the public half. Anyone with the statement and that public
half can check it. **They never have to ask us anything, and they never have to believe
us.**

---

## 3. What the receipt has to say

A signature proves a document is genuine. It says nothing about whether the document is
*useful*. You could sign "the Desk charged 1,500 rupees" and it would be genuine and
almost worthless — charged whom, for what, on whose say-so, when?

So the receipt binds four things together, and the word *together* is doing the work.
Each one alone is arguable:

**Who said this was allowed.** Somewhere behind this charge is a human who authorised it
before going to bed. There is a chain: the human said *you may buy coffee*, and separately
*you may spend up to 2,000 rupees*, and then one specific deal was struck under those two.
The receipt names all three links. Without them, the charge is money moved for no stated
reason.

The word *chain* is a promise, and it has to be one the code keeps. Naming three things in
one document does not make them connected; it just puts them next to each other. So before
signing anything, the code checks that the deal really was negotiated under that
authorisation to buy, and that the authorisation to *spend* really is the one paired with
it. Skip either check and you can produce a perfectly valid signature over a chain whose
links were never joined — and, worse, take the money off a ceiling belonging to somebody
who authorised none of it. This is not hypothetical; it is what a review of this ticket
found, and it is why both links are now checked here rather than assumed from the fact
that they arrived together.

**What was actually agreed.** The items, the quantities, the prices, and whatever else the
bargaining settled — who pays delivery, when payment is due. Without this, the chain
proves a human authorised *something*, not this.

**The amount actually charged.** This is the one that stops the two halves being pulled
apart. Terms saying 1,500 sitting next to a charge of 15,000 is precisely the case this
closes, and it closes it by putting both numbers inside one signature so they cannot be
separated.

**When, and the payment company's own reference numbers.** So the charge can be traced
back to the payment company's records by someone who has those and not ours.

---

## 4. Verifying it without us

Here is the part that is easy to fake and worth being strict about.

Suppose we write a signing routine and a checking routine, and then write a test where
our checker approves our signer's output. The test passes. What has it proved? That two
pieces of code we wrote agree with each other. If both are wrong in the same way — and
they would be, because the same person wrote them on the same afternoon — the test still
passes and the receipt is still worthless to a stranger.

The claim being made is *a stranger can verify this*. So the test has to be a stranger.

Every verification test in this ticket uses **jwcrypto**, a library written by other
people that we do not sign with and have no influence over. It is handed the receipt and
the Desk's published key and asked whether they match. Our own reading routine is
deliberately never called in that file. That is not fussiness; it is the difference
between testing the claim and testing something adjacent to it that always passes.

The same test file also does the obvious hostile thing: it takes a genuine receipt,
edits the amount from 1,500 to 150 the way somebody with a text editor would, and checks
that the third-party library refuses it. And it checks that a receipt does not verify
against *some other* Ed25519 key, because otherwise "it verifies" would be a claim about
the algorithm rather than about the Desk.

---

## 5. The three things that must never come apart

Settling one deal changes three things in the world:

1. the payment company takes the money,
2. a receipt comes into existence,
3. the running total spent against the human's ceiling goes up.

Any two of those happening without the third is a defect, and two of the combinations are
serious enough to design the whole thing around.

**Money taken with no receipt** is a charge the Desk cannot prove was owed. The buyer has
nothing to hold, and we have nothing to show the buyer.

**A receipt with no charge** is worse, and it is worth sitting with why. Everything
downstream trusts receipts — the treasury work counts them, the bank-matching work joins
against them. A receipt for money that never moved is a lie that propagates, and because
it is signed, it looks exactly as convincing as a true one.

**A ceiling drawn down by a charge that never happened** spends a human's authority on
nothing. The next honest request from that agent gets turned away, for a reason nobody
looking at it could work out.

So all three happen inside a single database transaction — either all of them commit or
none of them do. And the call to the payment company is *inside* that transaction, which
is an unusual thing to do and is worth naming as a cost.

**What it costs.** The row holding that human's running total stays locked for as long as
the payment company takes to answer. Two deals settling against the same authorisation at
the same moment queue up behind each other instead of running side by side.

**Why we pay it.** The alternative is: charge first, write it down afterwards. That leaves
a window — small, but real — in which the money has moved and the write fails. There is no
honest recovery from that state. A lock held across a network call is a performance
problem, and someone can fix it later with a redesign. Money charged that we cannot
account for is a correctness problem, and nobody can fix it afterwards at all.

Inside that transaction the order is chosen too: the ceiling is drawn down **before** the
payment company is called. Its refusal is the Desk's own rule, and the right time for the
Desk to refuse something is while there is still nothing to unwind.

---

## 6. When the charge does not go through

A card is declined. This is not a fault, it is Tuesday. It is also the single case the
correctness of this ticket turns on, so it gets said plainly:

> A charge that does not complete produces **no receipt** and leaves the running total
> **exactly where it was**.

Getting there is one line: the code leaves the transaction by raising, and leaving a
transaction that way is what undoes everything inside it. The ceiling is untouched
because it was never really touched — the draw-down was rolled back with everything else.

There is a wrinkle here that produced the only real bug in building this, and it is a nice
one. The first version caught that exception *inside* the transaction block instead of
outside it. Everything looked right. But catching it inside meant the block ended
normally, and a block that ends normally **commits** — so the money had not moved and the
ceiling had gone down anyway. The test asserting "the total is unchanged" is what found
it, immediately, which is roughly the argument for writing that test.

A third case sits beside those two and is not the same as either: the payment company
cannot be reached at all. Declined means *they said no*. Unreachable means *we do not
know*. The Desk must not record a guess about which. So the trail gets an entry saying an
attempt was made **before** the call goes out, written on its own transaction so it
survives the rollback — and a charge nobody ever heard back about leaves an attempt with
nothing after it, which is exactly what that situation should look like from outside.

That last sentence is only worth anything if a dangling attempt means *one* thing. Which
turns into a rule with some reach: **every settlement that starts gets an ending
written**, including the ones the Desk stops itself. There is a case where the Desk
begins settling and then refuses on its own account — the ceiling turns out to have less
left than the deal needs, which can happen because two deals raced. That refusal is
something the Desk knows about, so it writes an ending too. If it did not, the one
situation where the Desk is genuinely ignorant would be unreadable among several where it
is not.

The two kinds of ending are told apart by what is in them rather than by what they are
called: an ending the payment company produced carries its status and reference numbers,
and one the Desk produced carries none, because there was no call to carry them from.

---

## 7. Settling the same deal twice

Retrying is the ordinary reason anyone settles twice. A process restarts, a queue
redelivers, someone clicks again. Charging twice for one deal because of it would be
indefensible.

Two things stop it. The receipt is **named by the deal it settles** — its identifier is
the fingerprint of the agreed deal itself — so the database physically cannot hold two
receipts for one deal. And before charging anything, the code looks for a receipt that
already exists and hands it back if it finds one.

The lookup is the useful one; the database constraint is what holds if the lookup is
somehow wrong. Note the ordering: checking *after* charging would be too late, because the
money would already be gone by the time the constraint objected.

---

## 8. The payment company, and what test mode really allows

Charges go to **Razorpay**, in test mode. Test mode moves no real money, which is the
point rather than a compromise — what needs exercising is the sequence of calls and the
identifiers that come back, not the settling of actual funds.

There is an honest limit here, and hiding it would be the wrong call because a panel would
find it in a minute.

Razorpay has two objects: an *order*, which is the merchant saying what it wants paid, and
a *payment*, which is money against that order. A server can create an order. A server
**cannot** create a payment — that is made by the payer, in a browser, through Razorpay's
checkout page. Test mode included. So a headless run of this code creates a genuine order
with a genuine identifier and then honestly reports that nothing has been paid against it
yet. That is what Razorpay's API is, not a gap in the adapter.

This is most of the reason the payment company sits behind a **boundary** — one small
interface with a single method, `charge`, which any object can implement. The real adapter
is one implementation. The tests supply another that can be told to complete or to decline
on demand. That split matters twice over: the Desk's own behaviour on both outcomes gets
tested properly instead of depending on somebody else's server being up, and the handful
of tests that *do* go over the network are testing the one thing only they can test — that
the call sequence and the identifiers are real.

One small thing in that adapter is worth a sentence because it is the kind of thing that
loses money quietly. Razorpay takes amounts as whole **paise**, not rupees: 1,500.00
rupees is 150000. The conversion refuses anything finer than a paise rather than rounding
it. Rounding up and rounding down are both the Desk deciding to move a different amount of
money from the one that was agreed, so neither happens.

---

## 9. The key that has to outlive the process

The previous ticket generated the Desk's signing key when the program started, and said
so, and said this ticket would have to fix it.

It is worth seeing why that is not a detail. "Verifiable given the Desk's public key"
means nothing if restarting the Desk gives it a different key: every receipt it ever
issued would stop verifying against the key it now publishes, and there would be no way to
tell that from forgery. A receipt is a claim about something that happened. It has to stay
checkable after the process that signed it is gone.

So the Desk's keys are stored and loaded once, and the first Desk to start is the one that
creates them. Two Desks starting at the same instant race for it, and the loser adopts the
winner's key rather than overwriting it — overwriting would silently invalidate everything
signed before.

**The limitation, stated rather than dressed up:** the private halves sit unencrypted in
the same database as everything else. Anyone who can read that table can forge the Desk's
signature. A deployment that mattered would keep these in a dedicated key service and hand
the code a handle instead of a secret. This is not that, and calling the module a "vault"
does not make it that.

There are **two** keys, not one, and they are deliberately different types in the code so
that nothing can use one where it meant the other:

| Key | Signs | Scheme | Named | Why |
|:---|:---|:---|:---|:---|
| Mandate key | The closed deal the negotiation agreed | ES256 | `desk` | It is an AP2 document, and AP2's own toolkit can read nothing else |
| Receipt key | Receipts | Ed25519 | `desk-receipt` | A receipt is not an AP2 document, so the project's default scheme applies |

One says *the Desk agreed to this deal*. The other says *money moved and here is the
proof*. Holding the authority to say one should not be holding the authority to say the
other, and two unrelated classes is the cheapest way to make that a compile-time mistake
rather than a review comment somebody might miss.

The **Named** column is small and load-bearing, and it took a review to notice. Every
signed document carries, in its header, the name of the key that signed it. A stranger's
whole procedure is: read that name, look it up in the Desk's published set of keys, verify
with what comes back. Which only works if the name in the set is the name the key actually
signs with. Both keys originally announced themselves as `desk`, and the published set
listed them under tidy labels of our own invention — so the lookup found nothing, and the
one procedure the whole ticket is about did not work. The only reason the tests passed was
that they handed the right key straight to the verifier instead of looking it up. There is
now a test that does the lookup, because that is what a stranger would do.

---

## 10. Watching it happen

Two settlements of the same deal, differing only in what the payment company says. This is
the output of `tests/settlement/test_explainer_walkthrough.py`, asserted there so it
cannot drift from what the code does:

```
Two kilos of coffee at 750, and a rail that takes the money:

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
  settlement_incomplete  did not complete
```

Three things to notice.

The middle block is read out of the *signed bytes* by somebody else's library, after that
library confirmed the signature. Everything a dispute would turn on — what was agreed,
what was charged, which authorisations were behind it, which payment reference — is inside
what the signature covers. None of it had to be fetched from us.

`agreed 1500.00` and `charged 1500.00` are two separate claims sitting inside one
signature. Neither can be moved without the other.

And the second run: declined, no receipt, nothing drawn down. Not "drawn down and then
credited back" — the total was never changed at all.

---

## 11. Finding receipts again

Ticket 17 will take a credit landing in the bank account and work out which sales produced
it. It arrives holding an **amount** and a **date** and nothing else — no agent, no deal,
no authorisation. So those are the two ways into the receipt store, designed here rather
than there, because adding them later would mean a migration against a table full of
signed documents.

Two details in that store are load-bearing.

**An amount is never a number on its own.** Searching for 1,500 has to mean 1,500 *rupees*,
because matching a 1,500-rupee credit against a 1,500-dollar receipt would be a **false
match** — claiming a link that is not real. That is the one outcome the matching work must
never produce, and it is worse than finding no match at all, because it lets the treasury
believe in money that is not there.

**The columns are an index; the signed document is the truth.** Every column in that table
except the receipt itself restates something already inside the signed document. Nothing
reads a column and believes it — a query returns the signed document, verified against the
published key on the way out. So somebody with write access who edits a number in a column
does not get a query answering with a figure nobody signed. They get a refusal, loudly, at
the point of reading. There is a test that does exactly that.

---

## 12. The vocabulary, now that you need it

| Term | What it means here |
|:---|:---|
| **Receipt** | The Desk's signed statement that it charged a particular amount, under a particular authorisation, for particular terms, at a particular time. |
| **Mandate chain** | The three links from a human's authorisation to the money: what they were willing to buy, what they were willing to spend, and the one deal struck under both. |
| **Payment rail** | The company that actually moves the money. Razorpay here, behind an interface with one method. |
| **Accumulated total** | How much has been spent against one authorisation so far. The authorisation itself never changes; this is the Desk's own running count. |
| **A charge that did not complete** | The payment company declined, or nothing was paid. An outcome, not a fault, and one the Desk has a correct answer for. |
| **Published key** | The half of the Desk's secret that anyone may hold, and everything they need to check a receipt. |

Two words that are deliberately **not** used. A declined charge is never called a failure —
it is an ordinary outcome and naming it that way would eventually put it in a metric
counting things that went wrong. And a settlement that did not complete carries **no
reason code** in the trail: reason codes are the record of *the Desk refusing something*,
and the view built on them is read as exactly that. Somebody else's card being declined is
not us refusing anything, and letting it land in that view would make every refusal
statistic quietly wrong.

---

## 13. Where the code lives

`desk/settlement/` — six files, and each is one idea.

| File | What it holds |
|:---|:---|
| `rail.py` | The boundary. What the Desk asks a payment company for, what it gets back, and nothing about any particular company. |
| `razorpay_rail.py` | One implementation of that boundary. Orders, paise, and the honest limit in section 8. |
| `receipt.py` | The document: what goes into it, how it is signed, and what the Desk refuses to read back as one. |
| `store.py` | Where receipts are kept and how they are found by amount and by date. |
| `schema.py` | The table, and the constraints the database enforces rather than the code. |
| `settle.py` | The orchestration — the three things that must never come apart, in the order they happen. |

Plus `desk/identity/vault.py`, which is where the Desk's two keys live between restarts,
and the only place in `desk/identity/` that holds a private key at all.

---

## 14. What this ticket deliberately does not do

- **It does not refund, reverse or correct anything.** A receipt records something that
  happened; there is no revocation. Out of scope for the project, not deferred.
- **It does not read bank credits or match anything against them.** Tickets 16 to 18. This
  ticket is the reason that work is tractable at all: both sides of that join will be
  artefacts the Desk signed, which is what makes simple greedy matching sufficient where
  the general problem needs a solver.
- **It does not decide whether the Desk can afford to spend.** The treasury and its
  cleared-cash reasoning are ticket 15.
- **It does not handle more than one currency.** Rupees, and the adapter says so out loud
  rather than converting quietly.
- **It does not capture a payment headlessly.** It cannot; see section 8. What it does is
  create a real order against the real test-mode API and report honestly.
- **It does not decide when to settle.** Something has to hand it a closed deal. Today that
  is a test; ticket 19's seeded buyers and ticket 20's batch runner are what drive it at
  volume.

---

## 15. If you want to read the code

Start with `desk/settlement/__init__.py` — execution and proof, and why the second one is
the larger half. Then `settle.py`, which is where the three-things-together argument lives
next to the code that holds it.

The tests are the other way in, and they split along a line worth noticing.
`test_settling.py` drives whole deals through the four checks and a real negotiation and
then settles them, asserting on the receipt as an external object and on the audit trail —
never on a row in our own tables, because a test reading our own table would pass just as
happily if the signature covered nothing.
`test_third_party_verification.py` is the one that makes the actual claim, using somebody
else's library and nothing of ours.

**Counts, actually run:** 46 tests in `tests/settlement/` and 49 in `tests/identity/`
(6 of them the key store's). 457 in the suite as a whole, plus two skipped — the AP2
conformance test, which needs the throwaway environment `pyproject.toml` describes, and
the one Razorpay test that goes over the network, which skips unless test-mode credentials
are set.

Four existing files changed for reasons worth knowing. `tests/spine/test_no_model_call.py`
refuses to let a new package appear under `desk/` without somebody stating whether it is
part of checks 1 to 4; `settlement` is not, and is listed there with the reason — it calls
a third party over a network, which is the one dependency no check may ever have.
`desk/audit/vocabulary.py` gained two event types, which is a deliberate act against a
closed set. And `desk/spend/accumulator.py` and `desk/spend/check.py` had their imports
narrowed from `desk.mandate` to its individual modules: there was a circular import
between the two packages that had been latent, harmless only because the test suite
happened to load them in the surviving order. `import desk.mandate` on its own raised.
Naming the modules costs a line each and closes it.
