"""Registering an agent.

Acceptance criteria: registration issues an agent identity and writes to the trail,
and registration confers no spend authority on its own.
"""

from __future__ import annotations

import dataclasses
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from psycopg_pool import ConnectionPool

from desk.audit import AuditTrail, EventType
from desk.identity import AgentRegistry, PrincipalPublicKey, RegistrationConflict
from world.agents.keys import AgentKeypair


def test_registration_issues_an_identity(registry: AgentRegistry) -> None:
    before = datetime.now(UTC) - timedelta(seconds=5)
    keypair = AgentKeypair.generate()

    identity = registry.register(public_key=keypair.public_key, principal_id="principal-asha")

    assert identity.agent_id.startswith("agent-")
    assert identity.public_key == keypair.public_key
    assert identity.principal_id == "principal-asha"
    assert before <= identity.registered_at <= datetime.now(UTC) + timedelta(seconds=5)


def test_registration_writes_to_the_trail(registry: AgentRegistry, trail: AuditTrail) -> None:
    keypair = AgentKeypair.generate()

    identity = registry.register(public_key=keypair.public_key, principal_id="principal-asha")

    (entry,) = trail.query(event_type=EventType.AGENT_REGISTERED)
    assert entry.subject_id == identity.agent_id
    assert entry.reason_code is None
    assert entry.payload["evidence"]["public_key"] == keypair.public_key.base64url()
    assert entry.payload["evidence"]["key_algorithm"] == "EdDSA"
    assert entry.payload["evidence"]["principal_id"] == "principal-asha"
    assert trail.verify().ok


def test_the_identity_is_stable_across_sessions(registry: AgentRegistry) -> None:
    """A returning agent keeps the identity its key already earned."""
    keypair = AgentKeypair.generate()

    first = registry.register(public_key=keypair.public_key, principal_id="principal-asha")
    returning = registry.register(public_key=keypair.public_key, principal_id="principal-asha")

    assert returning == first


def test_a_returning_agent_is_recorded_once(registry: AgentRegistry, trail: AuditTrail) -> None:
    keypair = AgentKeypair.generate()

    registry.register(public_key=keypair.public_key, principal_id="principal-asha")
    registry.register(public_key=keypair.public_key, principal_id="principal-asha")

    assert len(trail.query(event_type=EventType.AGENT_REGISTERED)) == 1


def test_a_registered_key_cannot_change_the_principal_it_acts_for(registry: AgentRegistry) -> None:
    keypair = AgentKeypair.generate()
    registry.register(public_key=keypair.public_key, principal_id="principal-asha")

    with pytest.raises(RegistrationConflict):
        registry.register(public_key=keypair.public_key, principal_id="principal-ravi")


def test_two_agents_get_two_identities(registry: AgentRegistry) -> None:
    one = registry.register(
        public_key=AgentKeypair.generate().public_key, principal_id="principal-asha"
    )
    two = registry.register(
        public_key=AgentKeypair.generate().public_key, principal_id="principal-asha"
    )

    assert one.agent_id != two.agent_id


def test_a_registered_agent_is_found_by_its_identity(registry: AgentRegistry) -> None:
    keypair = AgentKeypair.generate()
    identity = registry.register(public_key=keypair.public_key, principal_id="principal-asha")

    assert registry.find(identity.agent_id) == identity


def test_an_unregistered_identity_is_not_found(registry: AgentRegistry) -> None:
    stranger = AgentKeypair.generate()

    assert registry.find(stranger.public_key.agent_id) is None


def test_a_principal_must_be_named(registry: AgentRegistry) -> None:
    with pytest.raises(ValueError):
        registry.register(public_key=AgentKeypair.generate().public_key, principal_id="  ")


def test_a_principal_key_cannot_stand_in_for_an_agent_key(registry: AgentRegistry) -> None:
    """The principal's key authorises spending; the agent's key only proves who asks.

    Structurally distinct types, so no path can accidentally treat one as the other.
    """
    principal_key = PrincipalPublicKey.from_base64url(
        AgentKeypair.generate().public_key.base64url()
    )

    with pytest.raises(TypeError):
        registry.register(
            public_key=principal_key,  # type: ignore[arg-type]
            principal_id="principal-asha",
        )


def test_registration_confers_no_spend_authority(
    registry: AgentRegistry, trail: AuditTrail
) -> None:
    """An identity, not trust. Nothing on it can be read as permission to spend."""
    keypair = AgentKeypair.generate()

    identity = registry.register(public_key=keypair.public_key, principal_id="principal-asha")

    assert {field.name for field in dataclasses.fields(identity)} == {
        "agent_id",
        "public_key",
        "principal_id",
        "registered_at",
    }
    (entry,) = trail.query()
    assert entry.event_type is EventType.AGENT_REGISTERED
    assert entry.payload["state_change"] == {"agent_identity": "issued", "spend_authority": "none"}


def test_the_registry_holds_no_private_key_material(
    registry: AgentRegistry, pool: ConnectionPool
) -> None:
    """The Desk holds its own private key and nobody else's."""
    keypair = AgentKeypair.generate()
    registry.register(public_key=keypair.public_key, principal_id="principal-asha")

    with pool.connection() as conn:
        columns = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                ("agent_identity",),
            ).fetchall()
        }
        (stored,) = conn.execute("SELECT public_key FROM agent_identity").fetchall()

    assert columns == {
        "agent_id",
        "public_key",
        "key_algorithm",
        "principal_id",
        "registered_at",
    }
    assert stored[0] == keypair.public_key.base64url()


def test_an_identity_and_its_record_arrive_together(
    registry: AgentRegistry, trail: AuditTrail, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A registered agent the trail never saw arrive is the trail disagreeing with reality."""

    def unwritable(*args: object, **kwargs: object) -> None:
        raise RuntimeError("the trail is unavailable")

    monkeypatch.setattr(AuditTrail, "record", unwritable)
    keypair = AgentKeypair.generate()

    with pytest.raises(RuntimeError):
        registry.register(public_key=keypair.public_key, principal_id="principal-asha")

    monkeypatch.undo()
    assert registry.find(keypair.public_key.agent_id) is None
    assert trail.query() == []


def test_one_agent_registering_many_times_at_once_arrives_once(
    registry: AgentRegistry, trail: AuditTrail
) -> None:
    """A restarted agent racing itself gets one identity, and the trail one arrival."""
    keypair = AgentKeypair.generate()

    def register() -> str:
        return registry.register(
            public_key=keypair.public_key, principal_id="principal-asha"
        ).agent_id

    with ThreadPoolExecutor(max_workers=8) as executor:
        issued = list(executor.map(lambda _: register(), range(8)))

    assert set(issued) == {keypair.public_key.agent_id}
    assert len(trail.query(event_type=EventType.AGENT_REGISTERED)) == 1
    assert trail.verify().ok
