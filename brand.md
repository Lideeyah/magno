# Brand — Magno

_Status: active. Defined from the product brief, not generated._

Magno is institutional trading infrastructure. The brand target is a Bloomberg
terminal that a designer got to touch: dense, monochromatic, numerically honest,
with exactly one accent doing all the signalling work.

## Palette

Monochromatic dark slate with a single cobalt accent. Cool-tinted greys
throughout — never warm, never mixed.

| Token | Hex | Role |
|---|---|---|
| `background` | `#080A0F` | Page ground |
| `surface` | `#0E121B` | Cards, panels |
| `surface-raised` | `#141926` | Nested panels, table headers, hover |
| `border` | `#1E2536` | All 1px hairlines |
| `border-strong` | `#2A3348` | Emphasised dividers, focus containers |
| `foreground` | `#F1F5F9` | Primary text |
| `muted` | `#8A97AD` | Secondary text — passes AA on all surfaces |
| `subtle` | `#5B6880` | Tertiary labels, axis ticks |
| `accent` | `#2563EB` | Primary actions, active state |
| `accent-bright` | `#3B82F6` | Hover, live indicators, data emphasis |
| `accent-dim` | `#1D3A8A` | Accent fills at low emphasis |
| `positive` | `#34D399` | Gains only |
| `negative` | `#EF4444` | Losses, rejections, hard blocks only |
| `warning` | `#F59E0B` | Drift warnings, degraded feeds |

### Accent discipline

Cobalt is the *only* decorative colour. Crimson `#EF4444` is reserved strictly
for error and rejection states — never for emphasis, never for a chart series
that merely happens to be third. Green appears only on realised or unrealised
gains. If something is neither an error nor a gain, it is grey.

## Typography

- **Geist Mono** — every number, symbol, gate code, timestamp and table cell.
  Always with `tabular-nums` so digits do not jitter as values tick.
- **Geist Sans** — prose, headings, body copy, marketing surfaces.
- Numeric telemetry never falls back to a proportional face. A P&L figure that
  reflows on every update reads as untrustworthy.

## Voice

Terse, quantitative, and never salesy. State the measurement, then the action.

- "Spread 7.2% exceeds 5.00% cap" — not "This trade looks risky!"
- "Net δ +2.41 → hedging" — not "Rebalancing your portfolio now..."
- Sentence case everywhere. No exclamation marks. No emoji in product surfaces.

Numbers carry their units and a consistent precision: Greeks to 3dp, dollars to
2dp, percentages to 2dp, IV rank as an integer out of 100.

## Motion

Sparse and functional. Duration tiers: 100ms colour/opacity feedback, 150ms
element entry, 200ms panel transitions. Nothing over 250ms. The delta dial
needle is the one continuously animated element in the product, because it is
the one number the operator watches for movement.

All motion is gated behind `prefers-reduced-motion: no-preference`.
