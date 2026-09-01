"use client";

import {
  Activity,
  ArrowDownToLine,
  Brain,
  CircleDot,
  Magnet,
  Radar,
  Receipt,
  ShieldCheck,
  Terminal,
  TriangleAlert,
  Zap,
} from "lucide-react";
import * as React from "react";

import { cn, clockTime } from "@/lib/format";
import type { AuditEvent, EventCategory, EventLevel, GateResult } from "@/lib/types";

import { Badge, EmptyState, Panel, Skeleton } from "./ui";

/**
 * The execution ledger.
 *
 * This is the artefact a reviewer reads to reconstruct the agent's behaviour,
 * so gate transcripts expand inline rather than being summarised away: when an
 * order is vetoed you can open the row and see every check that ran, what was
 * observed, and what the limit was.
 */

const CATEGORY_META: Record<
  EventCategory,
  { icon: React.ComponentType<{ className?: string }>; label: string }
> = {
  system: { icon: Terminal, label: "System" },
  scan: { icon: Radar, label: "Scan" },
  reasoning: { icon: Brain, label: "Reasoning" },
  gate: { icon: ShieldCheck, label: "Gate" },
  order: { icon: Receipt, label: "Order" },
  fill: { icon: CircleDot, label: "Fill" },
  hedge: { icon: Magnet, label: "Hedge" },
  shock: { icon: Zap, label: "Shock" },
  risk: { icon: TriangleAlert, label: "Risk" },
};

const LEVEL_STYLES: Record<EventLevel, { rail: string; title: string }> = {
  info: { rail: "bg-border-strong", title: "text-foreground" },
  success: { rail: "bg-positive", title: "text-foreground" },
  warn: { rail: "bg-warning", title: "text-warning" },
  error: { rail: "bg-negative", title: "text-negative" },
  reject: { rail: "bg-negative", title: "text-negative" },
};

const FILTERS: { key: "all" | EventCategory; label: string }[] = [
  { key: "all", label: "All" },
  { key: "reasoning", label: "Reasoning" },
  { key: "gate", label: "Gates" },
  { key: "order", label: "Orders" },
  { key: "hedge", label: "Hedges" },
  { key: "risk", label: "Risk" },
];

function GateTranscript({ gate }: { gate: GateResult }) {
  return (
    <ol className="mt-2 space-y-1 border-l border-border pl-3">
      {gate.checks.map((check, index) => (
        <li key={`${check.code}-${index}`} className="flex items-baseline gap-2 text-2xs">
          <span
            className={cn(
              "num w-11 shrink-0 font-medium",
              check.verdict === "REJECT"
                ? "text-negative"
                : check.verdict === "WARN"
                  ? "text-warning"
                  : "text-positive",
            )}
          >
            {check.verdict}
          </span>
          <span className="num shrink-0 text-subtle">{check.code}</span>
          <span className="min-w-0 flex-1 text-muted">{check.message}</span>
        </li>
      ))}
    </ol>
  );
}

function EventRow({ event }: { event: AuditEvent }) {
  const [open, setOpen] = React.useState(false);
  const meta = CATEGORY_META[event.category] ?? CATEGORY_META.system;
  const styles = LEVEL_STYLES[event.level] ?? LEVEL_STYLES.info;
  const Icon = meta.icon;

  const gate = (event.data?.gate ?? null) as GateResult | null;
  const origin = event.data?.origin as string | undefined;
  const expandable = Boolean(gate);

  const body = (
    <>
      <span className={cn("absolute left-0 top-0 h-full w-0.5", styles.rail)} aria-hidden="true" />
      <div className="flex items-start gap-2.5">
        <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-subtle" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <time className="num shrink-0 text-2xs text-subtle" dateTime={event.ts}>
              {clockTime(event.ts)}
            </time>
            <span className={cn("text-xs font-medium", styles.title)}>{event.title}</span>
            {origin && (
              <span className="num text-2xs text-subtle" title="Reasoning provider and latency">
                {origin}
              </span>
            )}
          </div>
          {event.detail && (
            <p className="mt-0.5 text-2xs leading-relaxed text-muted">{event.detail}</p>
          )}
          {open && gate && <GateTranscript gate={gate} />}
        </div>
      </div>
    </>
  );

  const className = cn(
    "relative block w-full py-2 pl-3 pr-3 text-left",
    "transition-colors duration-100 ease-enter",
  );

  if (!expandable) {
    return <li className={cn(className, "cursor-default")}>{body}</li>;
  }

  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className={cn(className, "hover:bg-surface-raised")}
      >
        {body}
        <span className="absolute right-3 top-2 text-2xs text-subtle">
          {open ? "Hide gates" : `${gate!.checks.length} gates`}
        </span>
      </button>
    </li>
  );
}

function ExecutionAuditStreamImpl({
  events,
  connected,
  className,
}: {
  events: AuditEvent[];
  connected: boolean;
  className?: string;
}) {
  const [filter, setFilter] = React.useState<"all" | EventCategory>("all");
  const [pinned, setPinned] = React.useState(true);
  const scrollRef = React.useRef<HTMLDivElement>(null);

  const visible = React.useMemo(
    () => (filter === "all" ? events : events.filter((e) => e.category === filter)),
    [events, filter],
  );

  // Auto-scroll, but only while the operator is already at the bottom. Yanking
  // the viewport while someone is reading history is the fastest way to make a
  // log feel hostile.
  React.useEffect(() => {
    if (!pinned) return;
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [visible.length, pinned]);

  const onScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const node = e.currentTarget;
    const atBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 40;
    setPinned(atBottom);
  };

  const jumpToLatest = () => {
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
    setPinned(true);
  };

  return (
    <Panel
      title="Execution stream"
      subtitle="Every scan, decision, gate verdict, order and hedge in sequence"
      className={className}
      bodyClassName="flex min-h-0 flex-col"
      action={
        <div className="flex items-center gap-1.5">
          <Activity
            className={cn("h-3 w-3", connected ? "text-positive" : "text-subtle")}
            aria-hidden="true"
          />
          <span className="num text-2xs text-subtle">{events.length}</span>
        </div>
      }
    >
      <div
        className="flex shrink-0 flex-wrap items-center gap-1 border-b border-border px-3 py-2"
        role="group"
        aria-label="Filter execution stream"
      >
        {FILTERS.map((option) => (
          <button
            key={option.key}
            type="button"
            onClick={() => setFilter(option.key)}
            aria-pressed={filter === option.key}
            className={cn(
              "h-7 rounded-control px-2 text-2xs font-medium",
              "transition-colors duration-100 ease-enter active:translate-y-px",
              filter === option.key
                ? "bg-surface-raised text-foreground ring-1 ring-inset ring-border-strong"
                : "text-muted hover:text-foreground",
            )}
          >
            {option.label}
          </button>
        ))}
      </div>

      <div className="relative min-h-0 flex-1">
        <div
          ref={scrollRef}
          onScroll={onScroll}
          className="h-full overflow-y-auto"
          role="log"
          aria-live="polite"
          aria-label="Agent execution log"
        >
          {events.length === 0 && !connected ? (
            <div className="space-y-3 p-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="space-y-1.5">
                  <Skeleton className="h-3 w-2/3" />
                  <Skeleton className="h-2.5 w-1/2" />
                </div>
              ))}
            </div>
          ) : visible.length === 0 ? (
            <EmptyState
              icon={Terminal}
              title={filter === "all" ? "No activity yet" : "Nothing in this category"}
              description={
                filter === "all"
                  ? "The ledger fills as the agent scans, reasons and executes. Engage the autopilot to start the loop."
                  : "Switch back to All to see the full sequence of agent activity."
              }
              action={
                filter !== "all" ? (
                  <button
                    type="button"
                    onClick={() => setFilter("all")}
                    className="text-xs text-accent-bright underline-offset-2 hover:underline"
                  >
                    Show all events
                  </button>
                ) : undefined
              }
            />
          ) : (
            <ul className="divide-y divide-border/60">
              {visible.map((event) => (
                <EventRow key={event.seq} event={event} />
              ))}
            </ul>
          )}
        </div>

        {!pinned && visible.length > 0 && (
          <button
            type="button"
            onClick={jumpToLatest}
            className={cn(
              "absolute bottom-3 left-1/2 flex h-8 -translate-x-1/2 items-center gap-1.5",
              "rounded-full border border-border-strong bg-surface-raised px-3 text-2xs text-foreground",
              "shadow-lg transition-colors duration-100 ease-enter hover:bg-border",
              "animate-fade-up",
            )}
          >
            <ArrowDownToLine className="h-3 w-3" aria-hidden="true" />
            Jump to latest
          </button>
        )}
      </div>
    </Panel>
  );
}

/** Only re-render when the ledger or the connection state actually changes. */
export const ExecutionAuditStream = React.memo(ExecutionAuditStreamImpl);
