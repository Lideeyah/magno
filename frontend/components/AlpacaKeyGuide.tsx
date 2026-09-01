"use client";

import { ChevronRight, ExternalLink, Info } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/format";

/**
 * In-product guide for obtaining Alpaca paper keys.
 *
 * Built as <details>/<summary> so keyboard navigation, Enter/Space toggling and
 * screen-reader semantics come from the platform rather than from hand-rolled
 * ARIA. The steps describe *locations* in the Alpaca dashboard rather than
 * exact pixel labels, so a vendor UI refresh degrades the guide instead of
 * breaking it.
 */

interface Step {
  title: string;
  body: React.ReactNode;
}

const STEPS: Step[] = [
  {
    title: "Create a free Alpaca account",
    body: (
      <>
        No funding, no deposit, no identity check needed for paper trading.{" "}
        <a
          href="https://alpaca.markets/"
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-0.5 text-accent-bright underline-offset-2 hover:underline"
        >
          alpaca.markets
          <ExternalLink className="h-2.5 w-2.5" aria-hidden="true" />
        </a>
      </>
    ),
  },
  {
    title: "Confirm you are in Paper Trading",
    body: (
      <>
        Open the{" "}
        <a
          href="https://app.alpaca.markets/dashboard/overview"
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-0.5 text-accent-bright underline-offset-2 hover:underline"
        >
          Alpaca dashboard
          <ExternalLink className="h-2.5 w-2.5" aria-hidden="true" />
        </a>
        . The selector in the top-left corner should read{" "}
        <span className="text-foreground">Paper Trading</span> with an account
        number starting <span className="num text-foreground">PA</span>. If it
        says Live, use the chevron on that selector to switch — live keys are
        rejected here.
      </>
    ),
  },
  {
    title: "Copy your key from the API Keys card",
    body: (
      <>
        In the right-hand sidebar, find the{" "}
        <span className="text-foreground">API Keys</span> card. Endpoint should read{" "}
        <span className="num text-foreground">paper-api.alpaca.markets</span>. The
        value under <span className="text-foreground">Key</span> — it starts with{" "}
        <span className="num text-foreground">PK</span> — goes in the first field
        below.
      </>
    ),
  },
  {
    title: "Press Regenerate to reveal the secret",
    body: (
      <>
        The secret is never displayed on the dashboard, only once at the moment you
        generate it. Press{" "}
        <span className="text-foreground">Regenerate</span> on that card and copy
        both values immediately.{" "}
        <span className="text-warning">
          This invalidates your previous key pair
        </span>{" "}
        — anything else using the old keys will stop working.
      </>
    ),
  },
  {
    title: "Options are already enabled",
    body: (
      <>
        Paper accounts ship with options trading on at{" "}
        <span className="text-foreground">Level 3</span>, so there is nothing to
        apply for — spreads and short premium all work. You can change it under
        Account → Configure if you want to test how Magno behaves at a lower level.
      </>
    ),
  },
  {
    title: "Confirm the $100k balance",
    body: (
      <>
        New paper accounts start at{" "}
        <span className="num text-foreground">$100,000</span>. Balances
        can&rsquo;t be edited in place, so if you&rsquo;ve been trading and want a
        clean baseline, open a fresh paper account from the account-number menu in
        the upper left. Magno will still run against whatever balance you have — it
        just flags the difference.
      </>
    ),
  },
];

export function AlpacaKeyGuide({ className }: { className?: string }) {
  return (
    <details
      className={cn(
        "group rounded-card border border-border bg-surface-raised/60",
        className,
      )}
    >
      <summary
        className={cn(
          "flex cursor-pointer list-none items-center gap-2 px-3 py-2.5",
          "text-xs font-medium text-foreground",
          "transition-colors duration-100 ease-enter hover:bg-surface-raised",
          "rounded-card focus-visible:outline-2",
          "[&::-webkit-details-marker]:hidden",
        )}
      >
        <ChevronRight
          className="h-3.5 w-3.5 shrink-0 text-subtle transition-transform duration-150 ease-move group-open:rotate-90"
          aria-hidden="true"
        />
        Where do I find these keys?
        <span className="ml-auto text-2xs font-normal text-subtle">
          about 1 minute
        </span>
      </summary>

      <div className="border-t border-border px-3 py-3">
        <ol className="space-y-3">
          {STEPS.map((step, index) => (
            <li key={step.title} className="flex gap-3">
              <span
                className={cn(
                  "num mt-px flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
                  "border border-border-strong bg-background text-2xs text-muted",
                )}
                aria-hidden="true"
              >
                {index + 1}
              </span>
              <div className="min-w-0">
                <p className="text-xs font-medium text-foreground">{step.title}</p>
                <p className="mt-0.5 text-2xs leading-relaxed text-muted">{step.body}</p>
              </div>
            </li>
          ))}
        </ol>

        <div className="mt-3 flex gap-2 rounded-card border border-border bg-background px-3 py-2.5">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-subtle" aria-hidden="true" />
          <p className="text-2xs leading-relaxed text-muted">
            <span className="text-foreground">Paper keys only.</span> Live keys are
            rejected — Magno builds its Alpaca client with{" "}
            <code className="num text-foreground">paper=True</code> unconditionally
            and has no code path to a live endpoint. Your keys are held in server
            memory for the life of the session, never written to disk and never
            logged.
          </p>
        </div>
      </div>
    </details>
  );
}
