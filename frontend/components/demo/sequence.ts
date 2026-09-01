/**
 * The 120-second demo sequence.
 *
 * Timings are declared once, here, so the progress bar, the stage list, the
 * spotlight and the narration can never disagree about where the run is. A
 * sequencer whose chrome drifts out of sync with its own content is worse than
 * no sequencer.
 */

export type StageId =
  | "HERO_DIAL"
  | "TELEMETRY_GRID"
  | "FEATHERLESS_REASONER"
  | "RISK_GATES"
  | "HEDGE_EXECUTION";

export interface Stage {
  id: StageId;
  index: number;
  label: string;
  /** Seconds from run start. */
  start: number;
  duration: number;
  headline: string;
  /** Read aloud, or shown as the narration line. */
  narration: string;
}

export const STAGES: Stage[] = [
  {
    id: "HERO_DIAL",
    index: 1,
    label: "Delta equilibrium",
    start: 0,
    duration: 20,
    headline: "Exposure is pinned to zero, continuously",
    narration:
      "The dial is the product. Portfolio delta sits at equilibrium, and any drift past the cap is corrected automatically with fractional equity orders.",
  },
  {
    id: "TELEMETRY_GRID",
    index: 2,
    label: "Live telemetry",
    start: 20,
    duration: 25,
    headline: "A real Alpaca paper account, read live",
    narration:
      "Equity, Greeks and open positions stream from Alpaca at one hertz. Every number here is computed from live quotes, not seeded.",
  },
  {
    id: "FEATHERLESS_REASONER",
    index: 3,
    label: "Featherless reasoner",
    start: 45,
    duration: 25,
    headline: "The model proposes from a closed menu",
    narration:
      "Featherless AI selects from contracts that already cleared every gate, so a symbol it invents can never become an order. Its disagreements with the quant baseline are recorded, not blocked.",
  },
  {
    id: "RISK_GATES",
    index: 4,
    label: "Risk gates",
    start: 70,
    duration: 25,
    headline: "Arithmetic decides, not the model",
    narration:
      "Nine deterministic checks run against a live quote at submission. Pure functions over plain data: no network, no clock, no model. The spread gate alone rejects most of the chain.",
  },
  {
    id: "HEDGE_EXECUTION",
    index: 5,
    label: "Hedge execution",
    start: 95,
    duration: 25,
    headline: "One deliberate correction, not a thousand",
    narration:
      "A single fractional order returned exposure to neutral. In-flight orders are counted so the same exposure is never hedged twice, and an order never crosses from long through zero into a short.",
  },
];

export const TOTAL_SECONDS = STAGES.reduce((sum, s) => sum + s.duration, 0);

export function stageAt(elapsed: number): Stage {
  for (const stage of STAGES) {
    if (elapsed < stage.start + stage.duration) return stage;
  }
  return STAGES[STAGES.length - 1];
}

/** 0–1 progress through the currently active stage. */
export function stageProgress(elapsed: number, stage: Stage): number {
  return Math.min(1, Math.max(0, (elapsed - stage.start) / stage.duration));
}

export function formatClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
