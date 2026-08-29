"""The principal directory: whose signatures the Desk will honour.

Small surface, and every test here is about the one thing it must never do -- let the
key behind a principal's name change quietly.
"""

from __future__ import annotations

import pytest
from psycopg_pool import ConnectionPool

from desk.identity import PrincipalConflict, PrincipalDirectory, PrincipalPublicKey
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair


@pytest.fixture
def directory(pool: ConnectionPool) -> PrincipalDirectory:
    return PrincipalDirectory(pool)


def test_an_enrolled_principal_is_found_by_name(directory: PrincipalDirectory) -> None:
    wallet = PrincipalKeypair.generate()

    enrolled = directory.enrol(principal_id="principal-asha", public_key=wallet.public_key)

    assert enrolled.public_key == wallet.public_key
    assert directory.find("principal-asha") == enrolled


def test_an_unenrolled_principal_is_not_found(directory: PrincipalDirectory) -> None:
    assert directory.find("principal-nobody") is None


def test_enrolling_the_same_key_twice_changes_nothing(directory: PrincipalDirectory) -> None:
    wallet = PrincipalKeypair.generate()

    first = directory.enrol(principal_id="principal-asha", public_key=wallet.public_key)
    again = directory.enrol(principal_id="principal-asha", public_key=wallet.public_key)

    assert again == first


def test_a_principal_cannot_be_moved_to_a_different_key(directory: PrincipalDirectory) -> None:
    """Rotation is real; doing it as a side effect of a lookup is not."""
    directory.enrol(
        principal_id="principal-asha", public_key=PrincipalKeypair.generate().public_key
    )

    with pytest.raises(PrincipalConflict, match="already enrolled under a different key"):
        directory.enrol(
            principal_id="principal-asha", public_key=PrincipalKeypair.generate().public_key
        )


def test_a_key_cannot_be_moved_to_a_different_principal(
    directory: PrincipalDirectory,
) -> None:
    """The other half of the same rule, and the one the key's own UNIQUE index enforces.

    Left uncaught this surfaced as a raw database exception -- with the key material in
    its message.
    """
    wallet = PrincipalKeypair.generate()
    directory.enrol(principal_id="principal-asha", public_key=wallet.public_key)

    with pytest.raises(PrincipalConflict, match="different principal") as refused:
        directory.enrol(principal_id="principal-someone-else", public_key=wallet.public_key)

    assert wallet.public_key.base64url() not in str(refused.value)


def test_an_off_curve_key_is_refused_where_it_is_built(
    directory: PrincipalDirectory,
) -> None:
    """Right length, right tag, not a point on P-256.

    Refused at construction rather than accepted, stored, and then raising from inside
    check 2 -- past the refusal path -- on every mandate for ever afterwards.
    """
    real = PrincipalKeypair.generate().public_key.material
    off_curve = real[:-1] + bytes([real[-1] ^ 0xFF])

    with pytest.raises(ValueError, match="not a point on P-256"):
        PrincipalPublicKey(off_curve)


def test_an_agent_key_cannot_stand_in_for_a_principal_key(
    directory: PrincipalDirectory,
) -> None:
    """The principal's key authorises spending; the agent's key only proves who asks."""
    with pytest.raises(TypeError):
        directory.enrol(
            principal_id="principal-asha",
            public_key=AgentKeypair.generate().public_key,  # type: ignore[arg-type]
        )


def test_a_principal_must_be_named(directory: PrincipalDirectory) -> None:
    with pytest.raises(ValueError):
        directory.enrol(principal_id="  ", public_key=PrincipalKeypair.generate().public_key)


def test_the_directory_holds_no_private_key_material(
    directory: PrincipalDirectory, pool: ConnectionPool
) -> None:
    """The column list is the whole guarantee, so a test asserts its shape."""
    directory.enrol(
        principal_id="principal-asha", public_key=PrincipalKeypair.generate().public_key
    )

    with pool.connection() as conn:
        columns = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                ("principal_key",),
            ).fetchall()
        }

    assert columns == {"principal_id", "public_key", "key_algorithm", "enrolled_at"}
