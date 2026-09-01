/** Shapes mirroring the FastAPI payloads in backend/app. */

export type Verdict = "PASS" | "REJECT" | "WARN";

export interface GateCheck {
  code: string;
  verdict: Verdict;
  message: string;
  observed: number | null;
  limit: number | null;
}

export interface GateResult {
  approved: boolean;
  summary: string;
  checks: GateCheck[];
}

export interface Greeks {
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  rho: number;
  iv: number;
  price: number;
}

export interface Account {
  account_id: string;
  account_number: string;
  status: string;
  equity: number;
  last_equity: number;
  cash: number;
  buying_power: number;
  options_buying_power: number;
  portfolio_value: number;
  long_market_value: number;
  short_market_value: number;
  options_trading_level: number;
  pattern_day_trader: boolean;
  trading_blocked: boolean;
  currency: string;
  day_pnl: number;
  day_pnl_pct: number;
}

export interface Position {
  symbol: string;
  underlying: string;
  asset_class: "us_option" | "us_equity";
  qty: number;
  market_value: number;
  unrealized_pl: number;
  avg_entry_price: number;
  current_price: number;
  strike: number | null;
  expiry: string | null;
  right: string | null;
  dte: number | null;
  greeks: Greeks | null;
  delta_exposure: number;
  gamma_exposure: number;
  theta_exposure: number;
  vega_exposure: number;
}

export interface UnderlyingExposure {
  underlying: string;
  spot: number;
  net_delta: number;
  net_gamma: number;
  net_theta: number;
  net_vega: number;
  option_delta: number;
  equity_delta: number;
  option_positions: number;
  delta_notional: number;
}

export interface PortfolioGreeks {
  net_delta: number;
  net_gamma: number;
  net_theta: number;
  net_vega: number;
  delta_notional: number;
  gross_option_positions: number;
  by_underlying: Record<string, UnderlyingExposure>;
}

export interface VolProfile {
  underlying: string;
  spot: number;
  atm_iv: number | null;
  realized_vol_20d: number | null;
  iv_rank: number | null;
  iv_premium: number | null;
  sample_size: number;
}

export interface ChainContract {
  symbol: string;
  underlying: string;
  right: "C" | "P";
  strike: number;
  expiry: string;
  dte: number;
  bid: number | null;
  ask: number | null;
  mid: number | null;
  last: number | null;
  spread_pct: number | null;
  open_interest: number | null;
  iv: number | null;
  iv_source: string;
  greeks: Greeks | null;
  greeks_source: string;
  spot: number;
  tradable: boolean;
  moneyness: number;
  gate?: GateResult;
}

export interface Order {
  id: string;
  client_order_id: string | null;
  symbol: string;
  asset_class: string | null;
  side: string;
  type: string;
  qty: number;
  filled_qty: number;
  filled_avg_price: number | null;
  limit_price: number | null;
  status: string;
  submitted_at: string | null;
  filled_at: string | null;
}

export type EventLevel = "info" | "success" | "warn" | "error" | "reject";
export type EventCategory =
  | "system"
  | "scan"
  | "reasoning"
  | "gate"
  | "order"
  | "fill"
  | "hedge"
  | "shock"
  | "risk";

export interface AuditEvent {
  seq: number;
  ts: string;
  category: EventCategory;
  level: EventLevel;
  title: string;
  detail: string;
  data: Record<string, unknown>;
}

export interface RiskEnvelope {
  max_spread_pct: number;
  max_allocation_pct: number;
  delta_drift_threshold: number;
  max_daily_loss_pct: number;
  max_open_positions: number;
  min_dte: number;
  max_dte: number;
  min_open_interest: number;
  min_option_price: number;
  max_option_price: number;
  iv_rank_sell_at: number | null;
  iv_rank_buy_at: number | null;
}

export interface SessionInfo {
  session_id: string;
  created_at: string;
  strategy: string;
  strategy_label: string;
  envelope: RiskEnvelope;
  contract_qty: number;
  autopilot: boolean;
  equity_at_open: number;
  shocks: Record<string, number>;
  cycle_count: number;
  universe: string[];
  account_number: string;
  account_id: string;
  options_trading_level: number;
  last_reasoning_at: string | null;
}

export interface HedgeState {
  threshold: number;
  net_delta: number;
  breach: boolean;
  utilisation: number;
  shocked: boolean;
  shocks: Record<string, number>;
}

export interface TelemetryFrame {
  type: "telemetry";
  ts: number;
  session: SessionInfo;
  account: Account;
  positions: Position[];
  greeks: PortfolioGreeks;
  clock: { is_open: boolean; next_open?: string; next_close?: string };
  orders: Order[];
  vol_surface: VolProfile[];
  hedge: HedgeState;
  errors: string[];
  events?: AuditEvent[];
}

export interface HedgeIntent {
  underlying: string;
  side: "buy" | "sell";
  qty: number;
  spot: number;
  notional: number;
  net_delta_before: number;
  projected_delta_after: number;
  reason: string;
  gate: GateResult | null;
}

export interface VerifyResult {
  valid: boolean;
  equity_verified: boolean;
  required_equity: number;
  account: Account;
  warnings: string[];
  endpoint: string;
}
