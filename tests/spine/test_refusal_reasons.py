"""Every refusal the deterministic spine can produce, reached through the front door.

The spine owns nine reason codes -- one for check 1, three for check 2, three for check
3, two for check 4 -- and a code nothing can reach is a code that does not exist. Each
test below builds a request that is valid in every respect but one, sends it, and
asserts on the reason and the position. The one-thing-wrong shape is deliberate: it is
what shows that each check refuses for its own reason rather than for a coincidence.

The tenth case has no reason code of its own on purpose. A request that names no price
is refused at check 3's position under check 3's code, for the same reason a mandate
naming no ceiling is: the Desk does not read an absent bound as an unlimited one.
"""

from __future__ import annotations

from decimal import Decimal

from desk.audit import AuditTrail, ReasonCode
from desk.identity import AgentIdentity
from desk.spine import ORDER, TrustSpine
from tests.freshness.conftest import DESK, WINDOW
from tests.mandate.conftest import execution_window
from tests.spine.conftest import LAPTOP, a_request, checks_recorded
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair

IDENTITY, MANDATE_VALIDITY, SPEND_AUTHORITY, REPLAY_AND_FRESHNESS = ORDER


def test_a_request_signed_by_an_unregistered_key_is_refused_at_check_one(
    spine: TrustSpine,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """``agent_signature_invalid``. Somebody else's key, our agent's name on the header."""
    outcome = spine.receive(a_request(wallet, agent, identity, signed_by=AgentKeypair.generate()))

    assert outcome.refused_at == IDENTITY
    assert outcome.reason_code is ReasonCode.AGENT_SIGNATURE_INVALID


def test_a_request_from_an_agent_the_desk_never_registered_is_refused_at_check_one(
    spine: TrustSpine,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """``agent_signature_invalid`` again, and that is the design rather than an oversight.

    An unregistered key and a forged signature get one answer on the wire, because
    telling them apart would tell a prober which half of the lie was believed. The trail
    is where they are told apart, and its reasoning says which this was.
    """
    stranger = AgentKeypair.generate()
    outcome = spine.receive(
        a_request(
            wallet, agent, identity, signed_by=stranger, claiming="agent-nobody-registered"
        )
    )

    assert outcome.refused_at == IDENTITY
    assert outcome.reason_code is ReasonCode.AGENT_SIGNATURE_INVALID
    assert "no agent is registered" in outcome.entries[0].payload["reasoning"]


def test_a_mandate_the_principal_did_not_sign_is_refused_at_check_two(
    spine: TrustSpine,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """``mandate_signature_invalid``. A wallet the Desk holds no key for signed these."""
    outcome = spine.receive(
        a_request(wallet, agent, identity, issued_by=PrincipalKeypair.generate())
    )

    assert outcome.refused_at == MANDATE_VALIDITY
    assert outcome.reason_code is ReasonCode.MANDATE_SIGNATURE_INVALID


def test_an_expired_mandate_is_refused_at_check_two(
    spine: TrustSpine,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """``mandate_expired``. A negative lifetime, so no test has to wait for a clock."""
    outcome = spine.receive(a_request(wallet, agent, identity, lifetime=-60))

    assert outcome.refused_at == MANDATE_VALIDITY
    assert outcome.reason_code is ReasonCode.MANDATE_EXPIRED


def test_a_mandate_bound_to_another_agent_is_refused_at_check_two(
    spine: TrustSpine,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """``agent_mandate_mismatch``, and the whole reason ``cnf`` is in AP2.

    The mandates are genuine, the principal really signed them, and our agent really
    holds the key it registered. What it does not hold is the key these mandates name --
    which is what a stolen mandate looks like, and why stealing one is not enough.
    """
    outcome = spine.receive(a_request(wallet, agent, identity, binds=AgentKeypair.generate()))

    assert outcome.refused_at == MANDATE_VALIDITY
    assert outcome.reason_code is ReasonCode.AGENT_MANDATE_MISMATCH


def test_asking_for_more_than_the_ceiling_is_refused_at_check_three(
    spine: TrustSpine,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """``exceeds_remaining_balance``. 5,000 against a ceiling of 2,000."""
    outcome = spine.receive(a_request(wallet, agent, identity, amount="5000.00"))

    assert outcome.refused_at == SPEND_AUTHORITY
    assert outcome.reason_code is ReasonCode.EXCEEDS_REMAINING_BALANCE


def test_asking_for_something_else_entirely_is_refused_at_check_three(
    spine: TrustSpine,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """``category_not_authorised``. A mandate for coffee is not a mandate for a laptop."""
    outcome = spine.receive(a_request(wallet, agent, identity, item_id=LAPTOP))

    assert outcome.refused_at == SPEND_AUTHORITY
    assert outcome.reason_code is ReasonCode.CATEGORY_NOT_AUTHORISED


def test_a_payment_outside_its_execution_window_is_refused_at_check_three(
    spine: TrustSpine,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """``outside_validity_window``. Authorised in January, presented long afterwards.

    Distinct from the expiry check 2 already ran: this mandate has not lapsed, and the
    principal simply did not authorise paying today.
    """
    outcome = spine.receive(
        a_request(
            wallet,
            agent,
            identity,
            execution=execution_window(
                not_before="2026-01-01T00:00:00+00:00", not_after="2026-01-31T00:00:00+00:00"
            ),
            execution_date="2026-01-15T00:00:00+00:00",
        )
    )

    assert outcome.refused_at == SPEND_AUTHORITY
    assert outcome.reason_code is ReasonCode.OUTSIDE_VALIDITY_WINDOW


def test_the_same_request_sent_twice_is_refused_at_check_four(
    spine: TrustSpine,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """``nonce_replayed``, and it is the identical bytes both times.

    Everything about the second send is valid -- same signature, same mandates, same
    price -- which is exactly what a captured request looks like when it is played back.
    """
    request = a_request(wallet, agent, identity)

    assert spine.receive(request).passed
    replayed = spine.receive(request)

    assert replayed.refused_at == REPLAY_AND_FRESHNESS
    assert replayed.reason_code is ReasonCode.NONCE_REPLAYED
    assert checks_recorded(trail) == [1, 2, 2, 3, 4, 4, 1, 2, 2, 3, 4]


def test_a_backdated_proof_of_possession_is_refused_at_check_four(
    spine: TrustSpine,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """``request_stale``. A fresh nonce on a hop older than the window the Desk honours."""
    outcome = spine.receive(
        a_request(wallet, agent, identity, hop_age=int(WINDOW.total_seconds()) + 60)
    )

    assert outcome.refused_at == REPLAY_AND_FRESHNESS
    assert outcome.reason_code is ReasonCode.REQUEST_STALE


def test_a_proof_of_possession_made_for_another_verifier_is_refused_at_check_four(
    spine: TrustSpine,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """``request_stale`` for an audience mismatch: a real signature we were never given."""
    outcome = spine.receive(a_request(wallet, agent, identity, audience="some-other-desk"))

    assert outcome.refused_at == REPLAY_AND_FRESHNESS
    assert outcome.reason_code is ReasonCode.REQUEST_STALE
    assert DESK in outcome.entries[-1].payload["reasoning"]


def test_one_nonce_across_both_mandates_refuses_the_second_half_of_the_request(
    spine: TrustSpine,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A nonce is honoured once per agent, and a request carries two proofs of possession.

    An agent that reuses one nonce across both hops has replayed itself. The Desk cannot
    tell that from a genuine replay and does not try to: it refuses, and the fix is on
    the agent's side and is trivial. The Checkout Mandate's hop is honoured first, so the
    refusal lands on the Payment Mandate's.
    """
    outcome = spine.receive(
        a_request(wallet, agent, identity, checkout_nonce="reused", payment_nonce="reused")
    )

    assert outcome.refused_at == REPLAY_AND_FRESHNESS
    assert outcome.reason_code is ReasonCode.NONCE_REPLAYED
    assert checks_recorded(trail) == [1, 2, 2, 3, 4, 4]


def test_a_request_naming_no_mandate_is_refused_where_the_mandate_would_have_been_read(
    spine: TrustSpine,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A validly signed request that is not a purchase request at all.

    Check 1 has nothing to object to: the signature is real and the agent is registered.
    What the body lacks is a mandate, and the check that reads mandates is the one that
    says so -- rather than a separate vocabulary of protocol refusals in front of the
    spine, saying almost the same thing in different words.
    """
    outcome = spine.receive(a_request(wallet, agent, identity, body={"hello": "desk"}))

    assert outcome.refused_at == MANDATE_VALIDITY
    assert outcome.reason_code is ReasonCode.MANDATE_SIGNATURE_INVALID
    assert checks_recorded(trail) == [1, 2]


def test_a_request_naming_no_price_is_refused_at_check_three(
    spine: TrustSpine,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """An unreadable price is not a free one.

    There is no emptiest amount of money -- zero is a number a mandate would happily
    authorise -- so this is the one field the spine cannot pass through to the check
    that reads it. It refuses at that check's position, under that check's code.
    """
    outcome = spine.receive(a_request(wallet, agent, identity, amount=None))

    assert outcome.refused_at == SPEND_AUTHORITY
    assert outcome.reason_code is ReasonCode.EXCEEDS_REMAINING_BALANCE
    assert checks_recorded(trail) == [1, 2, 2, 3]
    assert "unreadable price is not a free one" in outcome.entries[-1].payload["reasoning"]


def test_a_price_written_as_a_json_number_is_read_exactly(
    spine: TrustSpine,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """1000.10 stays 1000.10, which a float would not.

    AP2 types money as a JSON number, so a conformant agent may well write one. Request
    bodies are parsed the way mandate claims are, and the amount arrives as a ``Decimal``
    rather than as the nearest binary fraction to it.
    """
    outcome = spine.receive(a_request(wallet, agent, identity, raw_amount="1000.10"))

    assert outcome.passed
    assert outcome.request is not None
    assert outcome.request.amount is not None
    assert outcome.request.amount.amount == Decimal("1000.10")


def test_a_price_in_a_currency_the_mandate_does_not_authorise_is_refused_at_check_three(
    spine: TrustSpine,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """``category_not_authorised``. The Desk holds no exchange rate and invents none."""
    outcome = spine.receive(a_request(wallet, agent, identity, currency="USD"))

    assert outcome.refused_at == SPEND_AUTHORITY
    assert outcome.reason_code is ReasonCode.CATEGORY_NOT_AUTHORISED


def test_a_price_of_true_is_not_an_offer_of_one_rupee(
    spine: TrustSpine,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A ``bool`` is an ``int`` in Python, and an unguarded reader would take it for one.

    The refusal is the same as for an absent price, which is the right answer: ``true``
    is not an amount of money, and reading it as one rupee would let a request the agent
    never made pass check 3.
    """
    outcome = spine.receive(a_request(wallet, agent, identity, raw_amount="true"))

    assert outcome.refused_at == SPEND_AUTHORITY
    assert outcome.reason_code is ReasonCode.EXCEEDS_REMAINING_BALANCE
    assert "unreadable price is not a free one" in outcome.entries[-1].payload["reasoning"]


def test_a_price_in_a_currency_the_desk_cannot_read_is_refused_the_same_way(
    spine: TrustSpine,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A price is an amount *and* a currency, and half a price is no price.

    ``"inr"`` is not an ISO 4217 code, and an amount with no currency the Desk reads is
    a bare number it has no default to attach to. The refusal names both halves and the
    evidence shows what arrived in each, so the record does not say the amount was
    missing when it was the currency.
    """
    outcome = spine.receive(a_request(wallet, agent, identity, currency="inr"))

    assert outcome.refused_at == SPEND_AUTHORITY
    assert outcome.reason_code is ReasonCode.EXCEEDS_REMAINING_BALANCE

    evidence = outcome.entries[-1].payload["evidence"]
    assert evidence["stated"] == {"amount": "750.00", "currency": "inr"}

