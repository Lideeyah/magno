"use client";

import type {
  AuditEvent,
  ChainContract,
  GateResult,
  HedgeIntent,
  Order,
  PortfolioGreeks,
  SessionInfo,
  TelemetryFrame,
  VerifyResult,
  VolProfile,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_MAGNO_API?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

const SESSION_KEY = "magno.session";

export function getSessionId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(SESSION_KEY);
  } catch {
    // Private browsing or blocked site data; the session just won't persist.
    return null;
  }
}

export function setSessionId(id: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (id) window.localStorage.setItem(SESSION_KEY, id);
    else window.localStorage.removeItem(SESSION_KEY);
  } catch {
    /* non-fatal */
  }
}

export class ApiError extends Error {
  status: number;
  payload: unknown;

  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

function messageFrom(payload: unknown, fallback: string): string {
  if (typeof payload === "string") return payload;
  if (payload && typeof payload === "object") {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object") {
      const nested = detail as { error?: string; gate?: { summary?: string } };
      if (nested.error) return nested.error;
      if (nested.gate?.summary) return nested.gate.summary;
    }
    if (Array.isArray(detail) && detail.length) {
      // FastAPI validation errors.
      const first = detail[0] as { msg?: string; loc?: string[] };
      if (first?.msg) return `${first.loc?.slice(-1)[0] ?? "input"}: ${first.msg}`;
    }
  }
  return fallback;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  { auth = true }: { auth?: boolean } = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (auth) {
    const id = getSessionId();
    if (!id) {
      throw new ApiError("No active session. Reconnect your Alpaca account.", 401, null);
    }
    headers.set("X-Magno-Session", id);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(
      `Cannot reach the Magno backend at ${API_BASE}. Start it with "uvicorn app.main:app --port 8000".`,
      0,
      null,
    );
  }

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!response.ok) {
    if (response.status === 401 && auth) {
      // The session is gone server-side — most often because the backend
      // restarted, since sessions are held in memory only. Clear the stale id
      // so the terminal falls through to its guard instead of every control
      // failing one by one with no explanation.
      setSessionId(null);
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("magno:session-expired"));
      }
    }
    throw new ApiError(
      messageFrom(payload, `Request failed (${response.status})`),
      response.status,
      payload,
    );
  }
  return payload as T;
}

// --------------------------------------------------------------------------- //
// Session
// --------------------------------------------------------------------------- //
export interface OnboardPayload {
  api_key: string;
  secret_key: string;
  strategy: string;
  delta_drift_threshold: number;
  max_spread_pct: number;
  max_allocation_pct: number;
  max_daily_loss_pct: number;
  max_open_positions: number;
  contract_qty: number;
  min_dte: number;
  max_dte: number;
  iv_rank_sell_at: number | null;
  iv_rank_buy_at: number | null;
}

export const api = {
  health: () => request<Record<string, unknown>>("/health", {}, { auth: false }),

  verify: (api_key: string, secret_key: string) =>
    request<VerifyResult>(
      "/api/session/verify",
      { method: "POST", body: JSON.stringify({ api_key, secret_key }) },
      { auth: false },
    ),

  createSession: (payload: OnboardPayload) =>
    request<{ session_id: string; session: SessionInfo }>(
      "/api/session",
      { method: "POST", body: JSON.stringify(payload) },
      { auth: false },
    ),

  getSession: () => request<{ session: SessionInfo }>("/api/session"),

  endSession: () => request<{ ended: boolean }>("/api/session", { method: "DELETE" }),

  telemetry: () => request<TelemetryFrame>("/api/telemetry"),

  events: (limit = 150) => request<{ events: AuditEvent[] }>(`/api/events?limit=${limit}`),

  clearEvents: () => request<{ cleared: number }>("/api/events", { method: "DELETE" }),

  greeks: () =>
    request<{ greeks: PortfolioGreeks; positions: unknown[] }>("/api/greeks"),

  setAutopilot: (enabled: boolean) =>
    request<{ autopilot: boolean; session: SessionInfo }>("/api/autopilot", {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),

  updateEnvelope: (patch: Record<string, number>) =>
    request<{ envelope: SessionInfo["envelope"]; contract_qty: number }>("/api/envelope", {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  // ------------------------------------------------------------------ //
  // Market
  // ------------------------------------------------------------------ //
  scan: (underlyings?: string[]) =>
    request<{
      market_open: boolean;
      profiles: VolProfile[];
      approved: ChainContract[];
      rejected: { symbol: string; reasons: string[] }[];
      chain: ChainContract[];
      errors: string[];
    }>(`/api/scan${underlyings?.length ? `?underlyings=${underlyings.join(",")}` : ""}`),

  chain: (underlying: string, right?: "C" | "P") =>
    request<{
      underlying: string;
      spot: number | null;
      market_open: boolean;
      count: number;
      approved: number;
      contracts: ChainContract[];
    }>(`/api/chain/${underlying}${right ? `?right=${right}` : ""}`),

  volSurface: () =>
    request<{ profiles: VolProfile[]; errors: string[] }>("/api/vol-surface"),

  dryRun: () =>
    request<{
      dry_run: true;
      market_open: boolean;
      candidates: number;
      decision: {
        action: string;
        symbol: string | null;
        side: string;
        contracts: number;
        confidence: number;
        thesis: string;
        source: string;
        model: string | null;
        latency_ms: number | null;
      } | null;
      gate: GateResult | null;
      reason?: string;
    }>("/api/reason/dry-run", { method: "POST" }),

  // ------------------------------------------------------------------ //
  // Execution
  // ------------------------------------------------------------------ //
  submitOption: (symbol: string, side: "buy" | "sell", contracts: number, thesis = "") =>
    request<{ submitted: boolean; order: Order; limit_price: number }>("/api/orders/option", {
      method: "POST",
      body: JSON.stringify({ symbol, side, contracts, thesis }),
    }),

  hedge: (force = false) =>
    request<{
      hedged: boolean;
      net_delta: number;
      reason?: string;
      intents: HedgeIntent[];
      executed?: { intent: HedgeIntent; submitted: boolean; error?: string }[];
    }>("/api/orders/hedge", { method: "POST", body: JSON.stringify({ force }) }),

  orders: (limit = 50) => request<{ orders: Order[] }>(`/api/orders?limit=${limit}`),

  closePosition: (symbol: string) =>
    request<{ order: Order }>(`/api/positions/${encodeURIComponent(symbol)}/close`, {
      method: "POST",
    }),

  // ------------------------------------------------------------------ //
  // Shock simulation
  // ------------------------------------------------------------------ //
  shock: (underlying: string, pct: number) =>
    request<{
      shocks: Record<string, number>;
      delta_before: number;
      delta_after: number;
      greeks_before: PortfolioGreeks;
      greeks_after: PortfolioGreeks;
      intents: HedgeIntent[];
    }>("/api/simulate/shock", {
      method: "POST",
      body: JSON.stringify({ underlying, pct }),
    }),

  clearShocks: () =>
    request<{ shocks: Record<string, number>; cleared: Record<string, number> }>(
      "/api/simulate/shock",
      { method: "DELETE" },
    ),
};

export function telemetrySocketUrl(sessionId: string): string {
  const base = API_BASE.replace(/^http/, "ws");
  return `${base}/ws/telemetry?session_id=${encodeURIComponent(sessionId)}`;
}
