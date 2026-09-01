import Link from "next/link";

import { BentoMechanics } from "@/components/BentoMechanics";
import { ComparisonMatrix } from "@/components/ComparisonMatrix";
import { CountUp } from "@/components/CountUp";
import { GrainOverlay } from "@/components/GrainOverlay";
import { HeroDeltaDial } from "@/components/HeroDeltaDial";
import { LoopScrollytelling } from "@/components/LoopScrollytelling";
import { MagnoMark, Navbar } from "@/components/Navbar";
import { DrawRule, Reveal, RevealGroup, RevealItem } from "@/components/Reveal";
import { RevealHeadline } from "@/components/RevealHeadline";
import { TactileScrubber } from "@/components/TactileScrubber";
import { GITHUB_URL, SUBMISSION_URL } from "@/lib/site";

const STATS = [
  { to: 9, decimals: 0, label: "Deterministic gates", hint: "Enforced before any order is constructed" },
  { to: 5, decimals: 0, suffix: "s", label: "Hedge cadence", hint: "Risk correction never waits on the model" },
  { to: 0.001, decimals: 3, label: "Delta resolution", hint: "Fractional shares, not rounded lots" },
  { to: 136, decimals: 0, label: "Tests passing", hint: "Pricing identities, gate vetoes, hedge sizing" },
];

const RIGOR = [
  {
    code: "LOCAL_GREEKS_INVERSION",
    body: "Newton-Raphson implied-volatility solver with a bisection fallback in the wings. Never stalls when the broker returns null Greeks — which on paper accounts is most of the time.",
  },
  {
    code: "FASTMCP_SERVER",
    body: "One tool implementation, published over the Model Context Protocol. External agents drive the same code path as the autonomous loop, gates included.",
  },
  {
    code: "DETERMINISTIC_GATES",
    body: "Nine mathematical limits enforced in Python before any order is constructed. Pure functions over plain data — no network, no clock, no model.",
  },
  {
    code: "IMMUTABLE_LEDGER",
    body: "Every gate verdict and fill streams to an append-only audit log with the observed value and the limit it was measured against.",
  },
];

export default function LandingPage() {
  return (
    <div className="relative min-h-screen">
      <GrainOverlay />

      <div className="relative z-10">
        <Navbar />

        {/* -------------------------------------------------------------- */}
        {/* Hero                                                            */}
        {/* -------------------------------------------------------------- */}
        <section className="mx-auto max-w-7xl px-4 pb-20 pt-28 md:px-6 lg:px-8 lg:pt-36">
          <div className="grid gap-14 lg:grid-cols-[minmax(0,1fr)_24rem] lg:gap-16">
            <div className="max-w-2xl">
              <RevealHeadline
                className="text-balance text-4xl font-semibold leading-[1.06] tracking-tight text-foreground md:text-5xl lg:text-[3.4rem]"
                lines={["Autonomous options trading", "with hardwired risk limits."]}
              />

              <Reveal delay={0.18}>
                <p className="mt-6 max-w-xl text-base leading-relaxed text-muted">
                  Magno stops you bleeding capital on wide spreads and sudden market
                  swings. It continuously identifies mispriced volatility while
                  hardwired mathematical gates and automated rebalancing protect your
                  book — even while you sleep.
                </p>
              </Reveal>

              <Reveal delay={0.26}>
                <div className="mt-9 flex flex-wrap items-center gap-3">
                  <Link
                    href="/onboarding"
                    className="inline-flex h-11 items-center rounded-md bg-accent px-5 text-sm font-medium text-white transition-colors duration-100 hover:bg-accent-bright active:translate-y-px"
                  >
                    Launch Terminal
                  </Link>
                  <a
                    href="#simulator"
                    className="inline-flex h-11 items-center rounded-md border border-white/[0.12] px-5 text-sm font-medium text-foreground transition-colors duration-100 hover:border-white/25 hover:bg-white/[0.04] active:translate-y-px"
                  >
                    Test the Engine
                  </a>
                </div>

                <p className="num mt-5 text-2xs text-subtle">
                  Alpaca paper trading · $100,000 baseline · nothing to install
                </p>
              </Reveal>

              <DrawRule className="mt-12" />

              <RevealGroup
                as="dl"
                className="mt-8 grid grid-cols-2 gap-x-6 gap-y-6 sm:grid-cols-4"
              >
                {STATS.map((item) => (
                  <RevealItem key={item.label}>
                    <dt className="num text-2xs uppercase tracking-[0.14em] text-subtle">
                      {item.label}
                    </dt>
                    <dd className="num mt-1.5 text-2xl font-medium tabular-nums text-foreground">
                      <CountUp
                        to={item.to}
                        decimals={item.decimals}
                        suffix={item.suffix ?? ""}
                      />
                    </dd>
                    <dd className="mt-1 text-2xs leading-relaxed text-subtle">
                      {item.hint}
                    </dd>
                  </RevealItem>
                ))}
              </RevealGroup>
            </div>

            <Reveal delay={0.1} y={18} className="lg:pt-2">
              <HeroDeltaDial />
              <p className="mt-3 text-2xs leading-relaxed text-subtle">
                A live desk, not a mockup. The market underneath is walking on its own
                and the option is re-priced on every tick — the drift is real gamma, and
                the engine hedges it back without being asked.
              </p>
            </Reveal>
          </div>
        </section>

        {/* -------------------------------------------------------------- */}
        {/* The loop — pinned scroll narrative                              */}
        {/* -------------------------------------------------------------- */}
        <section
          id="mechanics"
          className="mx-auto max-w-7xl scroll-mt-20 px-4 py-16 md:px-6 lg:px-8"
        >
          <Reveal>
            <div className="max-w-2xl">
              <h2 className="text-2xl font-semibold tracking-tight text-foreground">
                The loop
              </h2>
              <p className="mt-3 text-sm leading-relaxed text-muted">
                Two clocks run side by side. Trade decisions every sixty seconds, risk
                correction every five. The fast one is deliberately deterministic — if
                the model is slow or unreachable, exposure is still being neutralised.
              </p>
            </div>
          </Reveal>

          <div className="mt-10">
            <LoopScrollytelling />
          </div>
        </section>

        {/* -------------------------------------------------------------- */}
        {/* Mechanics bento                                                 */}
        {/* -------------------------------------------------------------- */}
        <section className="mx-auto max-w-7xl px-4 py-16 md:px-6 lg:px-8">
          <Reveal>
            <div className="max-w-2xl">
              <h2 className="text-2xl font-semibold tracking-tight text-foreground">
                The mechanics
              </h2>
              <p className="mt-3 text-sm leading-relaxed text-muted">
                Three failures kill most autonomous options books. Magno is built around
                refusing each one.
              </p>
            </div>
          </Reveal>

          <Reveal delay={0.08} className="mt-10">
            <BentoMechanics />
          </Reveal>
        </section>

        {/* -------------------------------------------------------------- */}
        {/* Comparison                                                      */}
        {/* -------------------------------------------------------------- */}
        <section className="mx-auto max-w-7xl px-4 py-16 md:px-6 lg:px-8">
          <Reveal>
            <div className="max-w-2xl">
              <h2 className="text-2xl font-semibold tracking-tight text-foreground">
                Where autonomous books usually break
              </h2>
              <p className="mt-3 text-sm leading-relaxed text-muted">
                Each row is a specific failure mode, and a specific piece of code that
                refuses it.
              </p>
            </div>
          </Reveal>

          <Reveal delay={0.08} className="mt-10">
            <ComparisonMatrix />
          </Reveal>
        </section>

        {/* -------------------------------------------------------------- */}
        {/* Architecture                                                    */}
        {/* -------------------------------------------------------------- */}
        <section
          id="architecture"
          className="mx-auto max-w-7xl scroll-mt-20 px-4 py-16 md:px-6 lg:px-8"
        >
          <Reveal>
            <div className="max-w-2xl">
              <h2 className="text-2xl font-semibold tracking-tight text-foreground">
                Quantitative rigor
              </h2>
              <p className="mt-3 text-sm leading-relaxed text-muted">
                The model proposes. Arithmetic disposes. Handing an agent a trading
                account is only reasonable if the model cannot be the last word.
              </p>
            </div>
          </Reveal>

          <RevealGroup className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {RIGOR.map((item) => (
              <RevealItem
                key={item.code}
                className="rounded-lg border border-white/[0.08] p-5 transition-colors duration-150 hover:border-white/[0.16]"
              >
                <div className="num text-2xs tracking-tight text-accent-bright">
                  {item.code}
                </div>
                <p className="mt-3 text-xs leading-relaxed text-muted">{item.body}</p>
              </RevealItem>
            ))}
          </RevealGroup>
        </section>

        {/* -------------------------------------------------------------- */}
        {/* Simulator                                                       */}
        {/* -------------------------------------------------------------- */}
        <section
          id="simulator"
          className="mx-auto max-w-7xl scroll-mt-20 px-4 py-16 md:px-6 lg:px-8"
        >
          <Reveal>
            <div className="max-w-2xl">
              <h2 className="text-2xl font-semibold tracking-tight text-foreground">
                Stress-test the delta engine
              </h2>
              <p className="mt-3 text-sm leading-relaxed text-muted">
                Drag the market and watch exposure move. This is the same computation
                the terminal&rsquo;s shock simulator runs against a real Alpaca book.
              </p>
            </div>
          </Reveal>

          <Reveal delay={0.08} className="mt-10">
            <TactileScrubber />
          </Reveal>
        </section>

        {/* -------------------------------------------------------------- */}
        {/* Closing                                                         */}
        {/* -------------------------------------------------------------- */}
        <section className="mx-auto max-w-7xl px-4 py-16 md:px-6 lg:px-8">
          <Reveal>
            <div className="flex flex-wrap items-center justify-between gap-6 rounded-lg border border-white/[0.08] bg-surface p-8">
              <div className="max-w-xl">
                <h2 className="text-xl font-semibold tracking-tight text-foreground">
                  Your keys never leave your machine
                </h2>
                <p className="mt-2 text-sm leading-relaxed text-muted">
                  Credentials are held in memory for the life of the session — never
                  written to disk, never logged. The Alpaca client is constructed with{" "}
                  <code className="num text-foreground">paper=True</code>{" "}
                  unconditionally, so there is no code path to a funded account.
                </p>
              </div>
              <Link
                href="/onboarding"
                className="inline-flex h-11 shrink-0 items-center rounded-md bg-accent px-5 text-sm font-medium text-white transition-colors duration-100 hover:bg-accent-bright active:translate-y-px"
              >
                Launch Terminal
              </Link>
            </div>
          </Reveal>
        </section>

        {/* -------------------------------------------------------------- */}
        {/* Footer                                                          */}
        {/* -------------------------------------------------------------- */}
        <footer className="border-t border-white/[0.08]">
          <div className="mx-auto max-w-7xl px-4 py-8 md:px-6 lg:px-8">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <MagnoMark />
                <span className="hidden text-xs text-subtle sm:inline">
                  · Autonomous options delta-hedging infrastructure
                </span>
              </div>

              <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
                <Link
                  href="/terminal"
                  className="text-muted transition-colors duration-100 hover:text-white"
                >
                  Launch Terminal
                </Link>
                <a
                  href={GITHUB_URL}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="text-muted transition-colors duration-100 hover:text-white"
                >
                  GitHub Repository
                </a>
                <a
                  href={SUBMISSION_URL}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="text-muted transition-colors duration-100 hover:text-white"
                >
                  Lablab Submission
                </a>
              </div>
            </div>

            <p className="num mt-6 border-t border-white/[0.06] pt-5 text-2xs text-subtle">
              Verified on Alpaca Paper ($100k account baseline) · © 2026 Magno. Open
              source. Not investment advice.
            </p>
          </div>
        </footer>
      </div>
    </div>
  );
}
