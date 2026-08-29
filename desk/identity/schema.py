"""The two identity tables.

The registry holds what the Desk needs to answer "who is asking": the agent's public
key, the principal it claims to act for, the identity it was issued and when. The
principal directory holds what the Desk needs to answer "did a human really authorise
this": the principal's own public key. Neither holds **any private key material** --
the Desk holds its own key and nobody else's (CONTEXT.md section 7). The column lists
are the whole guarantee, so they are short on purpose and a test asserts their shape.

The two key columns have different widths because the two roles have different
signature schemes, and the CHECK constraints say so: an agent key is thirty-two raw
Ed25519 bytes, a principal key is a sixty-five byte uncompressed P-256 point. Storing
one where the other belongs is refused by the database, not merely by the code.

Registration state is deliberately not the audit trail's job. The trail records that
a registration happened; these tables are what the Desk reads on the next request.
"""

from __future__ import annotations

from typing import Any

from psycopg import Connection

from desk.identity.jws import AGENT_REQUEST_ALG
from desk.identity.keys import AGENT_ID_PREFIX

TABLE = "agent_identity"
PRINCIPAL_TABLE = "principal_key"

#: ES256, spelled out here rather than imported: ``principals.py`` imports this module,
#: so importing it back would close a cycle.
PRINCIPAL_KEY_ALG = "ES256"

#: Base64url of thirty-two bytes is forty-three characters; of sixty-five, eighty-seven.
_AGENT_KEY_CHARS = 43
_PRINCIPAL_KEY_CHARS = 87


def install_schema(conn: Connection[Any]) -> None:
    """Create the identity tables if they are not there. Idempotent."""
    conn.execute(_TABLE_DDL)
    conn.execute(_PRINCIPAL_TABLE_DDL)


_TABLE_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    agent_id      text PRIMARY KEY,
    public_key    text NOT NULL UNIQUE,
    key_algorithm text NOT NULL,
    principal_id  text NOT NULL,
    registered_at timestamptz NOT NULL,
    CONSTRAINT agent_identity_id_is_a_thumbprint
        CHECK (agent_id ~ '^{AGENT_ID_PREFIX}[A-Za-z0-9_-]{{43}}$'),
    CONSTRAINT agent_identity_key_is_base64url
        CHECK (public_key ~ '^[A-Za-z0-9_-]{{{_AGENT_KEY_CHARS}}}$'),
    CONSTRAINT agent_identity_algorithm_is_supported
        CHECK (key_algorithm = '{AGENT_REQUEST_ALG}'),
    CONSTRAINT agent_identity_principal_is_named
        CHECK (length(btrim(principal_id)) > 0)
)
"""

_PRINCIPAL_TABLE_DDL = f"""
CREATE TABLE IF NOT EXISTS {PRINCIPAL_TABLE} (
    principal_id  text PRIMARY KEY,
    public_key    text NOT NULL UNIQUE,
    key_algorithm text NOT NULL,
    enrolled_at   timestamptz NOT NULL,
    CONSTRAINT principal_key_is_named
        CHECK (length(btrim(principal_id)) > 0),
    CONSTRAINT principal_key_is_base64url
        CHECK (public_key ~ '^[A-Za-z0-9_-]{{{_PRINCIPAL_KEY_CHARS}}}$'),
    CONSTRAINT principal_key_algorithm_is_supported
        CHECK (key_algorithm = '{PRINCIPAL_KEY_ALG}')
)
"""
