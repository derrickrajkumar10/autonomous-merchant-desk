"""Check 1 - identity.

Acceptance criteria: a correctly signed request from a registered agent verifies; a
request from an unregistered key, a request altered after signing, and a request
signed by another registered agent's key are each refused with
``agent_signature_invalid``.

Every refusal is asserted on the trail, because the trail is what a red-team
operator, the metrics and the control room read. What the check returns is
convenience; what it recorded is the claim.
"""

from __future__ import annotations

import json
from typing import Any

from jwt.api_jws import encode as jws_encode
from jwt.api_jws import get_unverified_header
from jwt.utils import base64url_encode

from desk.audit import AuditTrail, EventType, ReasonCode
from desk.identity import AGENT_REQUEST_ALG, AgentRegistry, IdentityCheck
from world.agents.keys import AgentKeypair

BODY = {"sku": "COFFEE-1KG", "quantity": 2}


def _registered(registry: AgentRegistry, keypair: AgentKeypair) -> str:
    return registry.register(public_key=keypair.public_key, principal_id="principal-asha").agent_id


def _replace_body(request: str, body: dict[str, Any]) -> str:
    """The same header and signature over a body somebody swapped in transit."""
    header, _, signature = request.split(".")
    payload = base64url_encode(json.dumps(body).encode()).decode()
    return f"{header}.{payload}.{signature}"


def test_a_signed_request_from_a_registered_agent_verifies(
    registry: AgentRegistry, identity_check: IdentityCheck, trail: AuditTrail
) -> None:
    keypair = AgentKeypair.generate()
    agent_id = _registered(registry, keypair)

    outcome = identity_check.verify(keypair.sign_request(BODY, agent_id=agent_id))

    assert outcome.passed
    assert outcome.identity is not None
    assert outcome.identity.agent_id == agent_id
    assert outcome.body == BODY
    assert outcome.reason_code is None

    (entry,) = trail.query(event_type=EventType.CHECK_1_IDENTITY_PASSED)
    assert entry.subject_id == agent_id
    assert entry.reason_code is None
    assert entry.payload["check"] == 1
    assert trail.verify().ok


def test_agent_requests_are_signed_ed25519(registry: AgentRegistry) -> None:
    """Ed25519 for agent requests. The ES256 exception is the Checkout JWT alone."""
    keypair = AgentKeypair.generate()
    agent_id = _registered(registry, keypair)

    request = keypair.sign_request(BODY, agent_id=agent_id)

    assert get_unverified_header(request)["alg"] == "EdDSA"
    assert AGENT_REQUEST_ALG == "EdDSA"


def test_identifying_an_agent_is_not_authorising_it(
    registry: AgentRegistry, identity_check: IdentityCheck, trail: AuditTrail
) -> None:
    keypair = AgentKeypair.generate()
    agent_id = _registered(registry, keypair)

    identity_check.verify(keypair.sign_request(BODY, agent_id=agent_id))

    (entry,) = trail.query(event_type=EventType.CHECK_1_IDENTITY_PASSED)
    assert entry.payload["state_change"] == {"request": "identified"}


def test_a_request_from_an_unregistered_key_is_refused(
    identity_check: IdentityCheck, trail: AuditTrail
) -> None:
    stranger = AgentKeypair.generate()

    outcome = identity_check.verify(
        stranger.sign_request(BODY, agent_id=stranger.public_key.agent_id)
    )

    assert not outcome.passed
    assert outcome.identity is None
    assert outcome.body is None
    assert outcome.reason_code is ReasonCode.AGENT_SIGNATURE_INVALID

    (entry,) = trail.query(event_type=EventType.CHECK_1_IDENTITY_REFUSED)
    assert entry.reason_code is ReasonCode.AGENT_SIGNATURE_INVALID
    assert entry.payload["evidence"]["claimed_agent_id"] == stranger.public_key.agent_id
    assert trail.verify().ok


def test_a_request_altered_after_signing_is_refused(
    registry: AgentRegistry, identity_check: IdentityCheck, trail: AuditTrail
) -> None:
    keypair = AgentKeypair.generate()
    agent_id = _registered(registry, keypair)
    request = keypair.sign_request(BODY, agent_id=agent_id)

    outcome = identity_check.verify(_replace_body(request, {"sku": "COFFEE-1KG", "quantity": 200}))

    assert not outcome.passed
    assert outcome.body is None
    assert outcome.reason_code is ReasonCode.AGENT_SIGNATURE_INVALID

    (entry,) = trail.query(event_type=EventType.CHECK_1_IDENTITY_REFUSED)
    assert entry.subject_id == agent_id
    assert trail.verify().ok


def test_a_request_signed_by_another_registered_agent_is_refused(
    registry: AgentRegistry, identity_check: IdentityCheck, trail: AuditTrail
) -> None:
    """An identity is not transferable: one agent cannot speak as another."""
    asha = AgentKeypair.generate()
    ravi = AgentKeypair.generate()
    asha_id = _registered(registry, asha)
    _registered(registry, ravi)

    outcome = identity_check.verify(ravi.sign_request(BODY, agent_id=asha_id))

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.AGENT_SIGNATURE_INVALID

    (entry,) = trail.query(event_type=EventType.CHECK_1_IDENTITY_REFUSED)
    assert entry.subject_id == asha_id
    assert trail.verify().ok


def test_a_request_signed_with_another_algorithm_is_refused(
    registry: AgentRegistry, identity_check: IdentityCheck, trail: AuditTrail
) -> None:
    """A wrong-algorithm path is visible in the trail rather than silent (ADR-0002)."""
    keypair = AgentKeypair.generate()
    agent_id = _registered(registry, keypair)
    forged = jws_encode(
        json.dumps(BODY).encode(),
        "a-symmetric-secret-the-desk-never-shared",
        algorithm="HS256",
        headers={"kid": agent_id, "typ": "stitchai-request+jws"},
    )

    outcome = identity_check.verify(forged)

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.AGENT_SIGNATURE_INVALID

    (entry,) = trail.query(event_type=EventType.CHECK_1_IDENTITY_REFUSED)
    assert entry.payload["evidence"]["algorithm"] == "HS256"


def test_an_unsigned_request_is_refused(
    registry: AgentRegistry, identity_check: IdentityCheck, trail: AuditTrail
) -> None:
    keypair = AgentKeypair.generate()
    agent_id = _registered(registry, keypair)
    unsigned = jws_encode(
        json.dumps(BODY).encode(),
        "",
        algorithm="none",
        headers={"kid": agent_id, "typ": "stitchai-request+jws"},
    )

    outcome = identity_check.verify(unsigned)

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.AGENT_SIGNATURE_INVALID
    assert trail.query(event_type=EventType.CHECK_1_IDENTITY_REFUSED)


def test_a_request_signed_as_something_other_than_a_request_is_refused(
    registry: AgentRegistry, identity_check: IdentityCheck, trail: AuditTrail
) -> None:
    """A signature over one kind of document is not a signature over another."""
    keypair = AgentKeypair.generate()
    agent_id = _registered(registry, keypair)
    receipt_shaped = keypair.sign(
        json.dumps(BODY).encode(), agent_id=agent_id, typ="stitchai-receipt+jws"
    )

    outcome = identity_check.verify(receipt_shaped)

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.AGENT_SIGNATURE_INVALID
    assert trail.query(event_type=EventType.CHECK_1_IDENTITY_REFUSED)


def test_a_request_that_is_not_a_signed_message_is_refused(
    identity_check: IdentityCheck, trail: AuditTrail
) -> None:
    outcome = identity_check.verify("not-a-jws-at-all")

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.AGENT_SIGNATURE_INVALID

    (entry,) = trail.query(event_type=EventType.CHECK_1_IDENTITY_REFUSED)
    assert entry.subject_id
    assert trail.verify().ok


def test_a_correctly_signed_request_with_no_body_object_is_refused(
    registry: AgentRegistry, identity_check: IdentityCheck
) -> None:
    """A valid signature over something that is not a request body is still not one."""
    keypair = AgentKeypair.generate()
    agent_id = _registered(registry, keypair)

    outcome = identity_check.verify(keypair.sign(b'"COFFEE-1KG"', agent_id=agent_id))

    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.AGENT_SIGNATURE_INVALID


def test_every_refusal_states_why(
    registry: AgentRegistry, identity_check: IdentityCheck, trail: AuditTrail
) -> None:
    """A generic rejection proves nothing (CONTEXT.md section 5, principle 3)."""
    stranger = AgentKeypair.generate()

    identity_check.verify(stranger.sign_request(BODY, agent_id=stranger.public_key.agent_id))

    (entry,) = trail.query(reason_code=ReasonCode.AGENT_SIGNATURE_INVALID)
    assert entry.payload["check"] == 1
    assert entry.payload["reasoning"]
    assert entry.payload["state_change"] == {"request": "refused"}
