"""The execution audit stream.

Every decision Magno makes -- a scan, a model completion, a gate verdict, an
order, a fill, a hedge -- is appended here as a structured record and pushed to
the terminal over the telemetry websocket. The ledger is the product: a judge
should be able to read it top to bottom and reconstruct why the agent did what
it did, without reading the source.
"""

from __future__ import annotations

import asyncio
import itertools
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

MAX_EVENTS = 500

_counter = itertools.count(1)


class EventLevel(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARN = "warn"
    ERROR = "error"
    REJECT = "reject"


class EventCategory(str, Enum):
    SYSTEM = "system"
    SCAN = "scan"
    REASONING = "reasoning"
    GATE = "gate"
    ORDER = "order"
    FILL = "fill"
    HEDGE = "hedge"
    SHOCK = "shock"
    RISK = "risk"


@dataclass
class AuditEvent:
    seq: int
    ts: str
    category: EventCategory
    level: EventLevel
    title: str
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "category": self.category.value,
            "level": self.level.value,
            "title": self.title,
            "detail": self.detail,
            "data": self.data,
        }


class AuditLog:
    """A bounded, append-only ledger with an asyncio fan-out to websocket clients."""

    def __init__(self, maxlen: int = MAX_EVENTS) -> None:
        self._events: deque[AuditEvent] = deque(maxlen=maxlen)
        self._subscribers: set[asyncio.Queue[AuditEvent]] = set()

    def emit(
        self,
        category: EventCategory,
        level: EventLevel,
        title: str,
        detail: str = "",
        **data: Any,
    ) -> AuditEvent:
        event = AuditEvent(
            seq=next(_counter),
            ts=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            category=category,
            level=level,
            title=title,
            detail=detail,
            data=data,
        )
        self._events.append(event)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A slow terminal must never stall the trading loop; it will
                # resynchronise from the snapshot on the next telemetry tick.
                pass
        return event

    # Convenience wrappers keep call sites readable at the point of decision.
    def info(self, category: EventCategory, title: str, detail: str = "", **data: Any) -> AuditEvent:
        return self.emit(category, EventLevel.INFO, title, detail, **data)

    def success(self, category: EventCategory, title: str, detail: str = "", **data: Any) -> AuditEvent:
        return self.emit(category, EventLevel.SUCCESS, title, detail, **data)

    def warn(self, category: EventCategory, title: str, detail: str = "", **data: Any) -> AuditEvent:
        return self.emit(category, EventLevel.WARN, title, detail, **data)

    def error(self, category: EventCategory, title: str, detail: str = "", **data: Any) -> AuditEvent:
        return self.emit(category, EventLevel.ERROR, title, detail, **data)

    def reject(self, category: EventCategory, title: str, detail: str = "", **data: Any) -> AuditEvent:
        return self.emit(category, EventLevel.REJECT, title, detail, **data)

    def clear(self) -> int:
        """Drop every recorded event and start a fresh ledger.

        The sequence counter is module-global and keeps climbing, so ids never
        collide with anything a client is still holding — a stale row cannot
        reappear by matching the seq of a new one.
        """
        dropped = len(self._events)
        self._events.clear()
        return dropped

    def recent(self, limit: int = 120) -> list[dict]:
        events = list(self._events)[-limit:]
        return [e.as_dict() for e in events]

    def subscribe(self) -> asyncio.Queue[AuditEvent]:
        queue: asyncio.Queue[AuditEvent] = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[AuditEvent]) -> None:
        self._subscribers.discard(queue)
