"""Sessions must survive a backend restart.

Credentials live in process memory and die with the process. On a managed host
that happens routinely -- a redeploy, or an idle spin-down on a free tier -- and
without a resume path every operator re-enters their Alpaca keys each time.

These tests drive the real HTTP surface with Alpaca replaced by a stub, since
the broker call is orthogonal to what is under test: what matters is that the
encrypted token round-trips the risk configuration, that it is refused when
tampered with or issued under a different key, and that a session rebuilt from
it is indistinguishable from a freshly onboarded one.

    cd backend && .venv/bin/python -m pytest tests/test_session_resume.py -q
"""

from __future__ import annotations

import importlib

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.broker import AccountSnapshot

ONBOARD = {
    "api_key": "PKTESTKEY123456",
    "secret_key": "secretsecretsecret",
    "strategy": "adaptive_vrp",
    "delta_drift_threshold": 8.0,
    "max_spread_pct": 0.04,
    "max_open_positions": 3,
    "contract_qty": 2,
    # Must clear the exit engine's 21-day time stop or onboarding 422s.
    "min_dte": 28.0,
    "max_dte": 60.0,
}


def _account() -> AccountSnapshot:
    return AccountSnapshot(
        account_id="acct-1",
        account_number="PA3XYZ",
        status="ACTIVE",
        equity=100_000.0,
        last_equity=99_500.0,
        cash=50_000.0,
        buying_power=200_000.0,
        options_buying_power=100_000.0,
        portfolio_value=100_000.0,
        long_market_value=50_000.0,
        short_market_value=0.0,
        options_trading_level=3,
        pattern_day_trader=False,
        trading_blocked=False,
    )


@pytest.fixture
def client(monkeypatch):
    """App with a fixed session key and Alpaca stubbed out."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("MAGNO_SESSION_KEY", key)

    # The key is read at import time, so the module has to be reloaded after
    # the environment is set -- and the router reloaded after it, or it keeps
    # a reference to the previous module's Fernet instance.
    from app import session_token

    importlib.reload(session_token)
    from app.routers import telemetry as telemetry_router

    importlib.reload(telemetry_router)

    import app.main

    importlib.reload(app.main)

    async def fake_get_account(self):
        return _account()

    monkeypatch.setattr("app.broker.AlpacaBroker.get_account", fake_get_account)

    with TestClient(app.main.app) as c:
        c._magno_key = key  # noqa: SLF001 - handed to the restart test
        yield c


def test_onboarding_issues_a_resume_token(client):
    r = client.post("/api/session", json=ONBOARD)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["resume_token"], "onboarding must return a token to persist"
    # The token must not be a transparent encoding of the credentials.
    assert ONBOARD["api_key"] not in body["resume_token"]
    assert ONBOARD["secret_key"] not in body["resume_token"]


def test_session_survives_a_restart(client):
    """The whole point: rebuild a working session after every in-memory
    session has been destroyed."""
    token = client.post("/api/session", json=ONBOARD).json()["resume_token"]
    first_id = client.post("/api/session", json=ONBOARD).json()["session_id"]

    # Simulate the restart: drop every session, as a fresh process would.
    from app.state_store import store

    store._sessions.clear()  # noqa: SLF001

    assert client.get("/api/session", headers={"X-Magno-Session": first_id}).status_code == 401

    r = client.post("/api/session/resume", json={"resume_token": token})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["session_id"] != first_id, "resume must mint a fresh session id"

    # The risk configuration has to come back exactly, or the agent resumes
    # under different limits than the operator set.
    env = body["session"]["envelope"]
    assert env["delta_drift_threshold"] == ONBOARD["delta_drift_threshold"]
    assert env["max_open_positions"] == ONBOARD["max_open_positions"]
    assert env["max_spread_pct"] == ONBOARD["max_spread_pct"]
    assert env["min_dte"] == ONBOARD["min_dte"]
    assert body["session"]["contract_qty"] == ONBOARD["contract_qty"]
    assert body["session"]["strategy"] == ONBOARD["strategy"]

    # And the rebuilt session must actually authenticate.
    assert client.get("/api/session", headers={"X-Magno-Session": body["session_id"]}).status_code == 200


def test_resume_rotates_the_token(client):
    """Each resume returns a token, so the browser can keep storing the latest
    one rather than holding the original forever."""
    token = client.post("/api/session", json=ONBOARD).json()["resume_token"]
    body = client.post("/api/session/resume", json={"resume_token": token}).json()
    assert body["resume_token"]


def test_tampered_token_is_refused(client):
    token = client.post("/api/session", json=ONBOARD).json()["resume_token"]
    bad = token[:-6] + "AAAAAA"
    r = client.post("/api/session/resume", json={"resume_token": bad})
    assert r.status_code == 401
    # The reason must not distinguish tampering from expiry from a wrong key,
    # which would tell someone probing the endpoint what they had achieved.
    assert "no longer valid" in r.json()["detail"]


def test_token_from_a_different_key_is_refused(client, monkeypatch):
    """A token minted by another deployment -- or by this one before the key
    was rotated -- must not open a session."""
    from app import session_token

    foreign = Fernet(Fernet.generate_key())
    forged = foreign.encrypt(b'{"v":1,"api_key":"x","secret_key":"y","strategy":"adaptive_vrp"}').decode()

    r = client.post("/api/session/resume", json={"resume_token": forged})
    assert r.status_code == 401
    assert session_token.TOKEN_VERSION == 1


def test_expired_token_is_refused(client, monkeypatch):
    token = client.post("/api/session", json=ONBOARD).json()["resume_token"]

    from app import session_token

    # Anything older than the TTL is refused regardless of being otherwise valid.
    monkeypatch.setattr(session_token, "TOKEN_TTL_SECONDS", -1)
    r = client.post("/api/session/resume", json={"resume_token": token})
    assert r.status_code == 401
