"""Encrypted resume tokens, so a restart does not force re-onboarding.

Sessions live in process memory and die with the process. On a managed host
that is not an edge case but the normal cycle: Render's free tier spins a
service down after minutes of inactivity and wipes the filesystem with it, so
a disk-backed store would drop credentials just as reliably as memory does.

The state therefore lives where it survives all of that -- in the operator's
own browser -- but encrypted, so it is opaque to the client holding it. The
server issues a Fernet token at onboarding containing the credentials and the
risk configuration; the browser keeps it in localStorage and posts it back
when its session id is no longer recognised. Only the server can read it.

Fernet gives authenticated encryption: a token that has been altered by even
one byte fails to decrypt rather than decrypting to something attacker-chosen.
Tokens carry a timestamp and are rejected past TOKEN_TTL_SECONDS.

MAGNO_SESSION_KEY must be set and stable across restarts, or every restart
mints a new key and invalidates every outstanding token -- which is precisely
the problem this module exists to solve. A generated fallback key keeps local
development working without ceremony, and says loudly that it is doing so.
"""

from __future__ import annotations

import json
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# 30 days. Long enough that judging and demos never trip it, short enough that
# a token copied out of a browser does not stay live indefinitely.
TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60

# Bumped when the payload shape changes, so an old token is rejected cleanly
# instead of raising a KeyError somewhere further in.
TOKEN_VERSION = 1


class TokenError(Exception):
    """Raised when a resume token is unreadable, tampered with, or expired."""


def _load_key() -> bytes:
    configured = os.getenv("MAGNO_SESSION_KEY", "").strip()
    if configured:
        try:
            # Validates length and base64 alphabet; raises otherwise.
            Fernet(configured.encode())
            return configured.encode()
        except Exception:
            raise RuntimeError(
                "MAGNO_SESSION_KEY is not a valid Fernet key. Generate one with:\n"
                "  python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\""
            ) from None

    key = Fernet.generate_key()
    logger.warning(
        "MAGNO_SESSION_KEY is not set; generated an ephemeral key. Resume tokens "
        "will stop working the next time this process restarts. Set the variable "
        "in the deployment environment to make sessions durable."
    )
    return key


_fernet = Fernet(_load_key())


def issue(
    *,
    api_key: str,
    secret_key: str,
    strategy: str,
    contract_qty: int,
    envelope: dict,
) -> str:
    """Encrypt everything needed to rebuild a session without the operator
    re-entering credentials."""
    payload = {
        "v": TOKEN_VERSION,
        "api_key": api_key,
        "secret_key": secret_key,
        "strategy": strategy,
        "contract_qty": contract_qty,
        "envelope": envelope,
    }
    return _fernet.encrypt(json.dumps(payload).encode()).decode()


def read(token: str) -> dict:
    """Decrypt a resume token. Raises TokenError for anything unusable.

    Every failure mode is deliberately reported the same way. Distinguishing
    "expired" from "tampered" from "wrong key" would tell a caller probing the
    endpoint which of those it had achieved.
    """
    try:
        raw = _fernet.decrypt(token.encode(), ttl=TOKEN_TTL_SECONDS)
    except (InvalidToken, ValueError, TypeError) as exc:
        raise TokenError("This saved session is no longer valid. Reconnect to continue.") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TokenError("This saved session is no longer valid. Reconnect to continue.") from exc

    if not isinstance(payload, dict) or payload.get("v") != TOKEN_VERSION:
        raise TokenError("This saved session was issued by an older version. Reconnect to continue.")

    for required in ("api_key", "secret_key", "strategy"):
        if not payload.get(required):
            raise TokenError("This saved session is incomplete. Reconnect to continue.")

    return payload
