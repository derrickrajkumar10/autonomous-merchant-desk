"""The registry table.

It holds what the Desk needs to answer "who is asking": the agent's public key, the
principal it claims to act for, the identity it was issued and when. Nothing else,
and in particular **no private key material** -- the Desk holds its own key and
nobody else's (CONTEXT.md section 7). The column list is the whole guarantee, so it
is short on purpose and a test asserts its shape.

Registration state is deliberately not the audit trail's job. The trail records that
a registration happened; this table is what the Desk reads on the next request.
"""

from __future__ import annotations

from typing import Any

from psycopg import Connection

from desk.identity.jws import AGENT_REQUEST_ALG
from desk.identity.keys import AGENT_ID_PREFIX

TABLE = "agent_identity"


def install_schema(conn: Connection[Any]) -> None:
    """Create the registry if it is not there. Idempotent."""
    conn.execute(_TABLE_DDL)


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
        CHECK (public_key ~ '^[A-Za-z0-9_-]{{43}}$'),
    CONSTRAINT agent_identity_algorithm_is_supported
        CHECK (key_algorithm = '{AGENT_REQUEST_ALG}'),
    CONSTRAINT agent_identity_principal_is_named
        CHECK (length(btrim(principal_id)) > 0)
)
"""
