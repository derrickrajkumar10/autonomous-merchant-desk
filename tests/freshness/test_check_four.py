"""Check 4: is this happening now, or did it already happen?

One test per acceptance criterion on ticket 05, plus the trail entry each outcome
leaves. Every mandate is signed by a real wallet, presented with a real key-binding JWT
signed by the agent, and verified by check 2 before it reaches check 4 -- because a
proof of possession checked against a key nobody had established would prove nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from psycopg_pool import ConnectionPool

from desk.audit import AuditTrail, EventType, ReasonCode
from desk.freshness import (
    FRESHNESS_WINDOW_VARIABLE,
    FreshnessCheck,
    FreshnessPolicy,
    NonceStore,
)
from desk.identity import AgentIdentity
from desk.mandate import MandateCheck
from tests.freshness.conftest import DESK, SKEW, WINDOW, present
from tests.mandate.conftest import a_mandate
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair


def test_a_replayed_nonce_is_refused_even_though_everything_else_is_valid(
    freshness_check: FreshnessCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The headline criterion. The second presentation is valid, and that is the point.

    Nothing distinguishes a replay from the request it copies except that the Desk has
    seen it before, so this is the one refusal that cannot be reached by reading the
    request more carefully -- only by remembering.
    """
    first = present(mandate_check, wallet, agent, identity, nonce="nonce-once")
    again = present(mandate_check, wallet, agent, identity, nonce="nonce-once")

    honoured = freshness_check.evaluate(first, presented_by=identity)
    replayed = freshness_check.evaluate(again, presented_by=identity)

    assert honoured.passed
    assert not replayed.passed
    assert replayed.reason_code is ReasonCode.NONCE_REPLAYED
    assert replayed.entry.event_type is EventType.CHECK_4_REPLAY_FRESHNESS_REFUSED
    assert replayed.entry.payload["evidence"]["nonce"] == "nonce-once"


def test_a_timestamp_outside_the_window_is_refused_even_though_the_nonce_is_fresh(
    freshness_check: FreshnessCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
    nonces: NonceStore,
) -> None:
    """The other half of the pair, and the one that makes captured traffic decay.

    The nonce is one the Desk has never seen, so nothing in the replay store can refuse
    this. Only the clock can. And a request refused for being stale does not spend its
    nonce -- burning it would mean an honest agent whose clock was wrong could never
    retry with a value it had already put on the wire.
    """
    stale = present(mandate_check, wallet, agent, identity, nonce="nonce-never-seen", hop_age=3600)

    outcome = freshness_check.evaluate(stale, presented_by=identity)

    assert outcome.reason_code is ReasonCode.REQUEST_STALE
    assert "stale" in outcome.entry.payload["reasoning"]
    assert outcome.entry.payload["evidence"]["window_seconds"] == int(WINDOW.total_seconds())
    assert not nonces.has_seen("nonce-never-seen", agent_id=identity.agent_id)


def test_a_hop_dated_in_the_future_is_refused_as_readily_as_an_old_one(
    freshness_check: FreshnessCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A window bounded at one end is not a window.

    An agent whose proofs are dated an hour ahead would otherwise hold a presentation
    that stays fresh for the length of the lie.
    """
    ahead = present(mandate_check, wallet, agent, identity, hop_age=-3600)

    assert freshness_check.evaluate(ahead, presented_by=identity).reason_code is (
        ReasonCode.REQUEST_STALE
    )


def test_freshness_reads_the_mandate_layer_as_well_as_the_hop(
    freshness_check: FreshnessCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """Three cases, one point: ``iat``/``exp`` and ``nonce``/``aud`` are two layers.

    A mandate with no ``exp`` is one AP2 permits and check 2 cannot bound -- only the
    hop's own age stops it being presented for ever. A hop minted *after* the mandate
    lapsed is the mirror image: recent handover, expired authority, and check 2's
    expiry test compares ``exp`` to now rather than to the hop. A hop dated *before*
    the mandate proves possession of something that did not exist yet.
    """
    eternal = present(mandate_check, wallet, agent, identity, lifetime=None, hop_age=3600)
    after_lapse = present(
        mandate_check, wallet, agent, identity, lifetime=10, hop_age=-20, mandate_age=0
    )
    before_authority = present(mandate_check, wallet, agent, identity, mandate_age=-600)

    assert freshness_check.evaluate(eternal, presented_by=identity).reason_code is (
        ReasonCode.REQUEST_STALE
    )

    lapsed = freshness_check.evaluate(after_lapse, presented_by=identity)
    assert lapsed.reason_code is ReasonCode.REQUEST_STALE
    assert "lapsed" in lapsed.entry.payload["reasoning"]

    early = freshness_check.evaluate(before_authority, presented_by=identity)
    assert early.reason_code is ReasonCode.REQUEST_STALE
    assert "before the mandate" in early.entry.payload["reasoning"]


def test_seen_nonces_survive_a_restart(
    freshness_check: FreshnessCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
    database_url: str,
    policy: FreshnessPolicy,
) -> None:
    """ "The Desk was restarted" is not a reason a replay should work.

    A second pool over the same database is what a restarted process gets: new
    connections, new objects, nothing carried over in memory. The nonce is still spent.
    """
    first = present(mandate_check, wallet, agent, identity, nonce="nonce-across-restart")
    again = present(mandate_check, wallet, agent, identity, nonce="nonce-across-restart")
    assert freshness_check.evaluate(first, presented_by=identity).passed

    with ConnectionPool(database_url, min_size=1, max_size=2, open=True) as restarted:
        after_restart = FreshnessCheck(NonceStore(restarted), AuditTrail(restarted), policy)
        outcome = after_restart.evaluate(again, presented_by=identity)

    assert outcome.reason_code is ReasonCode.NONCE_REPLAYED


def test_the_freshness_window_is_configurable_without_a_code_change(
    nonces: NonceStore,
    trail: AuditTrail,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """One presentation, two deployments, two verdicts -- and no code between them.

    The same hop, ninety seconds old, is stale to a Desk configured for sixty seconds
    and current to one configured for an hour. FR-3.4 asks for a short *configurable*
    window, and a window that can only be changed by editing ``check.py`` is not one.
    """
    settings = {"STITCHAI_DESK_AUDIENCE": DESK}
    strict = FreshnessCheck(
        nonces,
        trail,
        FreshnessPolicy.from_environment(settings | {FRESHNESS_WINDOW_VARIABLE: "60"}),
    )
    relaxed = FreshnessCheck(
        nonces,
        trail,
        FreshnessPolicy.from_environment(settings | {FRESHNESS_WINDOW_VARIABLE: "3600"}),
    )

    to_strict = present(mandate_check, wallet, agent, identity, hop_age=90)
    to_relaxed = present(mandate_check, wallet, agent, identity, hop_age=90)

    assert strict.evaluate(to_strict, presented_by=identity).reason_code is (
        ReasonCode.REQUEST_STALE
    )
    assert relaxed.evaluate(to_relaxed, presented_by=identity).passed


def test_a_proof_made_for_another_verifier_is_not_ours(
    freshness_check: FreshnessCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A real signature, by the right key, over the right presentation, and still no.

    Without the audience test, a Desk could honour a proof of possession an agent made
    while presenting the same mandate to somebody else entirely.
    """
    elsewhere = present(mandate_check, wallet, agent, identity, audience="some-other-merchant")

    outcome = freshness_check.evaluate(elsewhere, presented_by=identity)

    assert outcome.reason_code is ReasonCode.REQUEST_STALE
    assert "some-other-merchant" in outcome.entry.payload["reasoning"]


def test_a_hop_lifted_onto_another_presentation_is_refused(
    freshness_check: FreshnessCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """``sd_hash`` is what stops a fresh proof being reused on a different mandate.

    Both mandates are this principal's and both bind this agent, so every other check
    passes on the pair. Only the digest inside the hop says which presentation the
    agent was actually holding when it signed.
    """
    other = present(mandate_check, wallet, agent, identity)
    assert other.presentation is not None
    lifted = present(
        mandate_check,
        wallet,
        agent,
        identity,
        onto=other.presentation.rpartition("~")[0] + "~",
    )

    outcome = freshness_check.evaluate(lifted, presented_by=identity)

    assert outcome.reason_code is ReasonCode.REQUEST_STALE
    assert "different presentation" in outcome.entry.payload["reasoning"]


def test_a_presentation_with_no_hop_at_all_is_refused(
    freshness_check: FreshnessCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A bare mandate carries no nonce and no timestamp, so it may be presented for ever.

    This is the shape checks 1 to 3 are perfectly happy with, which is exactly why
    check 4 refuses it rather than treating key binding as optional.
    """
    bare = mandate_check.verify(a_mandate(wallet, agent), presented_by=identity)
    assert bare.passed

    outcome = freshness_check.evaluate(bare, presented_by=identity)

    assert outcome.reason_code is ReasonCode.REQUEST_STALE
    assert "no key-binding JWT" in outcome.entry.payload["reasoning"]


def test_a_hop_signed_by_the_wrong_key_is_refused(
    freshness_check: FreshnessCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The hop has to be signed by the key the mandate endorses, or it proves nothing.

    A stranger's signature over the right presentation is not the agent proving it holds
    its key; it is somebody else proving they hold theirs.
    """
    honest = present(mandate_check, wallet, agent, identity)
    assert honest.presentation is not None
    sd_jwt = honest.presentation.rpartition("~")[0] + "~"
    impostor = AgentKeypair.generate().present(sd_jwt, audience=DESK)

    forged = mandate_check.verify(impostor, presented_by=identity)
    assert forged.passed

    outcome = freshness_check.evaluate(forged, presented_by=identity)

    assert outcome.reason_code is ReasonCode.REQUEST_STALE
    assert "does not verify" in outcome.entry.payload["reasoning"]


def test_the_entry_carries_both_layers_and_the_policy_it_was_decided_under(
    freshness_check: FreshnessCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """ "Fresh" is an assertion until the instants and the window are in the entry too.

    The policy is recorded on every outcome, so a refusal read back next month says
    what the window was at the time rather than what it is now.
    """
    outcome = freshness_check.evaluate(
        present(mandate_check, wallet, agent, identity, nonce="nonce-recorded"),
        presented_by=identity,
    )
    entry = outcome.entry

    assert entry.event_type is EventType.CHECK_4_REPLAY_FRESHNESS_PASSED
    assert entry.subject_id == identity.agent_id
    assert entry.reason_code is None
    assert entry.payload["check"] == 4
    assert entry.payload["evidence"]["nonce"] == "nonce-recorded"
    assert entry.payload["evidence"]["audience"] == DESK
    assert entry.payload["evidence"]["window_seconds"] == int(WINDOW.total_seconds())
    assert entry.payload["evidence"]["clock_skew_seconds"] == int(SKEW.total_seconds())
    assert entry.payload["evidence"]["mandate_expires_at"] is not None
    assert entry.payload["evidence"]["key_binding_issued_at"] is not None
    assert entry.payload["state_change"] == {"nonce": "spent", "request": "fresh"}


def test_check_four_will_not_run_on_a_mandate_that_did_not_verify(
    freshness_check: FreshnessCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A refusal is an answer already; a later check on it would invent a second one."""
    refused = mandate_check.verify("not-a-mandate~", presented_by=identity)
    assert not refused.passed

    with pytest.raises(ValueError, match="did not verify"):
        freshness_check.evaluate(refused, presented_by=identity)


def test_spent_nonces_are_forgotten_only_once_the_window_would_refuse_them(
    freshness_check: FreshnessCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
    nonces: NonceStore,
) -> None:
    """The store is trimmed to the same horizon the window enforces, and no further.

    A nonce inside the window is still needed: its presentation would still be honoured
    if the store had forgotten it. One outside is not: that presentation is refused as
    stale before any nonce is read.
    """
    recent = present(mandate_check, wallet, agent, identity, nonce="nonce-recent")
    assert freshness_check.evaluate(recent, presented_by=identity).passed
    nonces.claim(
        "nonce-ancient",
        agent_id=identity.agent_id,
        audience=DESK,
        presented_at=datetime.now(UTC) - timedelta(days=1),
    )

    forgotten = freshness_check.forget_spent_nonces()

    assert forgotten == 1
    assert nonces.has_seen("nonce-recent", agent_id=identity.agent_id)
    assert not nonces.has_seen("nonce-ancient", agent_id=identity.agent_id)


def test_an_honest_agent_generates_its_own_nonce(
    freshness_check: FreshnessCheck,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """Two presentations a moment apart are two requests, not one repeated.

    The nonce is the agent's to choose until the Desk has a boundary to issue a
    challenge over (ticket 30), so the default has to be fresh every time or an honest
    agent would refuse itself on its second request.
    """
    first = freshness_check.evaluate(
        present(mandate_check, wallet, agent, identity), presented_by=identity
    )
    second = freshness_check.evaluate(
        present(mandate_check, wallet, agent, identity), presented_by=identity
    )

    assert first.passed and second.passed
    assert first.key_binding is not None and second.key_binding is not None
    assert first.key_binding.nonce != second.key_binding.nonce
