"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getSessionId, telemetrySocketUrl } from "./api";
import type { AuditEvent, TelemetryFrame } from "./types";

export type ConnectionStatus =
  | "idle"
  | "connecting"
  | "live"
  | "reconnecting"
  | "offline"
  | "unauthorized";

const MAX_EVENTS = 400;
const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 15_000;

/**
 * Single live channel for the terminal.
 *
 * The socket carries two message kinds: full `telemetry` frames on a fixed
 * cadence, and `event` messages pushed the instant the agent logs a decision.
 * Events are merged by sequence number so a reconnect that replays the recent
 * ledger cannot duplicate rows already on screen.
 *
 * Connection lifecycle is scoped entirely to one effect run. An earlier version
 * kept the "did we close this deliberately" flag on a hook-level ref, which
 * React StrictMode's mount/unmount/remount cycle turned into a socket leak: the
 * second mount reset the flag before the first socket's `onclose` arrived, so a
 * deliberate teardown was misread as a dropped connection and triggered a
 * reconnect *alongside* the socket that had just replaced it. Sockets then
 * accumulated instead of replacing each other, and each one pushed its own
 * frames until React's nested-update limit tripped.
 *
 * Everything mutable therefore lives inside the effect closure, and every
 * callback checks it still belongs to the current socket before touching state.
 */
export function useTelemetry() {
  const [frame, setFrame] = useState<TelemetryFrame | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  // Populated by the effect so the caller can force a reconnect without the
  // connection logic having to live outside the effect scope.
  const reconnectRef = useRef<() => void>(() => {});

  const mergeEvents = useCallback((incoming: AuditEvent[]) => {
    setEvents((prev) => {
      if (incoming.length === 0) return prev;
      const bySeq = new Map<number, AuditEvent>();
      for (const e of prev) bySeq.set(e.seq, e);

      let changed = false;
      for (const e of incoming) {
        if (!bySeq.has(e.seq)) changed = true;
        bySeq.set(e.seq, e);
      }
      // Returning the previous array when nothing is new lets React bail out of
      // the re-render entirely.
      if (!changed) return prev;

      return Array.from(bySeq.values())
        .sort((a, b) => a.seq - b.seq)
        .slice(-MAX_EVENTS);
    });
  }, []);

  useEffect(() => {
    let disposed = false;
    let active: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;

    const open = () => {
      if (disposed) return;

      const sessionId = getSessionId();
      if (!sessionId) {
        setStatus("unauthorized");
        setError("No active session. Complete onboarding to connect an Alpaca account.");
        return;
      }

      setStatus(attempt === 0 ? "connecting" : "reconnecting");

      let socket: WebSocket;
      try {
        socket = new WebSocket(telemetrySocketUrl(sessionId));
      } catch {
        setStatus("offline");
        setError("Could not open the telemetry socket.");
        return;
      }
      active = socket;

      // True only while this socket is both current and not torn down.
      const current = () => !disposed && active === socket;

      socket.onopen = () => {
        if (!current()) return;
        attempt = 0;
        setStatus("live");
        setError(null);
      };

      socket.onmessage = (message) => {
        if (!current()) return;
        try {
          const payload = JSON.parse(message.data as string);
          if (payload.type === "telemetry") {
            setFrame(payload as TelemetryFrame);
            if (Array.isArray(payload.events)) mergeEvents(payload.events);
          } else if (payload.type === "event" && payload.event) {
            mergeEvents([payload.event as AuditEvent]);
          } else if (payload.type === "error") {
            // Sent just before the server closes with an application code.
            setError(String(payload.detail ?? "The telemetry stream reported an error."));
          }
        } catch {
          // A malformed frame is not worth tearing the connection down for.
        }
      };

      socket.onerror = () => {
        if (!current()) return;
        setError("Telemetry socket error. Confirm the backend is running.");
      };

      socket.onclose = (event) => {
        // A superseded or torn-down socket must never schedule a reconnect.
        if (!current()) return;
        active = null;

        if (event.code === 4401) {
          setStatus("unauthorized");
          setError("This session expired. Reconnect your Alpaca account to continue.");
          return;
        }

        attempt += 1;
        const delay = Math.min(RECONNECT_BASE_MS * 2 ** (attempt - 1), RECONNECT_MAX_MS);
        setStatus("reconnecting");
        setError(`Connection lost. Retrying in ${Math.round(delay / 1000)}s…`);
        timer = setTimeout(open, delay);
      };
    };

    reconnectRef.current = () => {
      if (disposed) return;
      attempt = 0;
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      const previous = active;
      active = null; // detaches the old socket's handlers before closing it
      previous?.close();
      open();
    };

    open();

    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
      const socket = active;
      active = null;
      socket?.close();
    };
  }, [mergeEvents]);

  const reconnect = useCallback(() => reconnectRef.current(), []);

  /** Optimistically append a locally generated note to the ledger. */
  const pushLocalEvent = useCallback(
    (event: Omit<AuditEvent, "seq" | "ts"> & Partial<Pick<AuditEvent, "ts">>) => {
      mergeEvents([
        {
          // Negative sequence keeps local notes ordered before any server row
          // and guarantees they can never collide with a real seq.
          seq: -Date.now(),
          ts: event.ts ?? new Date().toISOString(),
          ...event,
        } as AuditEvent,
      ]);
    },
    [mergeEvents],
  );

  return { frame, events, status, error, reconnect, pushLocalEvent };
}
