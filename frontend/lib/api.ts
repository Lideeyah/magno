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

/* Encrypted resume token from onboarding.
 *
 * Sessions live in the backend's memory, and on a managed host that memory is
 * cleared routinely -- a redeploy, or an idle spin-down on a free tier. Without
 * this the operator re-enters their Alpaca keys every time that happens.
 *
 * The value is a Fernet token: the browser cannot read it, and only the server
 * that issued it can. Storing it here is what makes a session outlive the
 * process that created it. */
const RESUME_KEY = "magno.resume";

export function getResumeToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(RESUME_KEY);
  } catch {
    return null;
  }
}

export function setResumeToken(token: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (token) window.localStorage.setItem(RESUME_KEY, token);
    else window.localStorage.removeItem(RESUME_KEY);
  } catch {
    /* non-fatal */
  }
}

/* One in-flight resume at a time.
 *
 * A terminal mount fires several requests at once, so a restart produces a
 * burst of simultaneous 401s. Without this they would each post the same token
 * and each create a session, orphaning all but the last. */
let resumeInFlight: Promise<boolean> | null = null;

async function tryResume(): Promise<boolean> {
  const token = getResumeToken();
  if (!token) return false;
  if (resumeInFlight) return resumeInFlight;

  resumeInFlight = (async () => {
    try {
      const res = await fetch(`${API_BASE}/api/session/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resume_token: token }),
      });
      if (!res.ok) {
        // 401 means the token itself is dead -- expired, or minted under a key
        // this server no longer has. Anything else (Alpaca down, keys revoked)
        // may recover, so the token is kept.
        if (res.status === 401) setResumeToken(null);
        return false;
      }
      const data = (await res.json()) as { session_id?: string; resume_token?: string };
      if (!data.session_id) return false;
      setSessionId(data.session_id);
      if (data.resume_token) setResumeToken(data.resume_token);
      return true;
    } catch {
      return false;
    } finally {
      resumeInFlight = null;
    }
  })();

  return resumeInFlight;
}

/** Rebuild the session from the stored token. Returns false when there is
 *  nothing to resume from, which means the operator must onboard again.
 *  Exported for the telemetry socket, which authenticates by query parameter
 *  and so cannot go through `request`. */
export const attemptResume = tryResume;

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
  { auth = true, retried = false }: { auth?: boolean; retried?: boolean } = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (auth) {
    let id = getSessionId();
    // No id but a saved token: the backend restarted and cleared the id on a
    // previous call. Rebuild the session before giving up on the request.
    if (!id && !retried && (await tryResume())) id = getSessionId();
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
      // restarted, since sessions are held in memory only. If a resume token
      // is held, rebuild the session and replay the request once; the operator
      // never sees the interruption.
      if (!retried && (await tryResume())) {
        return request<T>(path, init, { auth, retried: true });
      }
      // Nothing to resume from, or the token is dead. Clear the stale id so
      // the terminal falls through to its guard instead of every control
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

  createSession: async (payload: OnboardPayload) => {
    const result = await request<{
      session_id: string;
      session: SessionInfo;
      resume_token?: string;
    }>("/api/session", { method: "POST", body: JSON.stringify(payload) }, { auth: false });
    // Persisted immediately: if the backend restarts before the operator does
    // anything else, this is the only thing that can rebuild the session.
    if (result.resume_token) setResumeToken(result.resume_token);
    return result;
  },

  getSession: () => request<{ session: SessionInfo }>("/api/session"),

  endSession: async () => {
    const result = await request<{ ended: boolean }>("/api/session", { method: "DELETE" });
    // Ending a session must not leave a token behind that would silently
    // resurrect it on the next request.
    setResumeToken(null);
    return result;
  },

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
