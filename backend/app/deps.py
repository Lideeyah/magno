"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from .state_store import SessionState, store

SESSION_HEADER = "X-Magno-Session"


async def require_session(
    x_magno_session: str | None = Header(default=None, alias=SESSION_HEADER),
) -> SessionState:
    state = store.get(x_magno_session)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No active Magno session. Complete onboarding to connect your Alpaca paper account.",
        )
    return state


SessionDep = Depends(require_session)
