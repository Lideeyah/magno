"use client";

import { AlertTriangle, Loader2 } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/format";

/* -------------------------------------------------------------------------- */
/* Button                                                                     */
/* -------------------------------------------------------------------------- */
type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md" | "lg";

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-white hover:bg-accent-bright disabled:hover:bg-accent border border-accent",
  secondary:
    "bg-surface-raised text-foreground hover:bg-border border border-border-strong",
  ghost:
    "bg-transparent text-muted hover:text-foreground hover:bg-surface-raised border border-transparent",
  danger:
    "bg-transparent text-negative hover:bg-negative/10 border border-negative/40",
};

const SIZES: Record<ButtonSize, string> = {
  // pt is 1px under pb: cap-height sits below the box top, so equal padding
  // reads as bottom-heavy.
  sm: "h-9 px-3 pt-[7px] pb-2 text-xs gap-1.5",
  md: "h-10 px-4 pt-[9px] pb-2.5 text-sm gap-2",
  lg: "h-11 px-5 pt-[11px] pb-3 text-sm gap-2",
};

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { className, variant = "secondary", size = "md", loading, disabled, children, ...props },
    ref,
  ) => (
    <button
      ref={ref}
      type="button"
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex select-none items-center justify-center rounded-control font-medium",
        "transition-[background-color,border-color,color,transform] duration-100 ease-enter",
        "active:translate-y-px",
        "disabled:pointer-events-none disabled:opacity-50",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...props}
    >
      {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
      {children}
    </button>
  ),
);
Button.displayName = "Button";

/* -------------------------------------------------------------------------- */
/* Panel                                                                      */
/* -------------------------------------------------------------------------- */
export function Panel({
  title,
  subtitle,
  action,
  className,
  bodyClassName,
  children,
}: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={cn("panel flex min-h-0 flex-col overflow-hidden", className)}>
      {(title || action) && (
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0">
            {title && (
              <h2 className="truncate text-xs font-medium uppercase tracking-[0.08em] text-muted">
                {title}
              </h2>
            )}
            {subtitle && (
              <p className="mt-0.5 truncate text-2xs text-subtle">{subtitle}</p>
            )}
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </header>
      )}
      <div className={cn("min-h-0 flex-1", bodyClassName)}>{children}</div>
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/* Stat                                                                       */
/* -------------------------------------------------------------------------- */
export function Stat({
  label,
  value,
  hint,
  tone = "neutral",
  size = "md",
  className,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: "neutral" | "positive" | "negative" | "accent" | "warning";
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const toneClass = {
    neutral: "text-foreground",
    positive: "text-positive",
    negative: "text-negative",
    accent: "text-accent-bright",
    warning: "text-warning",
  }[tone];

  const sizeClass = { sm: "text-sm", md: "text-lg", lg: "text-2xl" }[size];

  return (
    <div className={cn("min-w-0", className)}>
      <div className="th truncate">{label}</div>
      <div className={cn("num mt-1 truncate font-medium", sizeClass, toneClass)}>
        {value}
      </div>
      {hint && <div className="mt-0.5 truncate text-2xs text-subtle">{hint}</div>}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Badge                                                                      */
/* -------------------------------------------------------------------------- */
export function Badge({
  children,
  tone = "neutral",
  className,
}: {
  children: React.ReactNode;
  tone?: "neutral" | "positive" | "negative" | "accent" | "warning";
  className?: string;
}) {
  const tones = {
    neutral: "border-border-strong bg-surface-raised text-muted",
    positive: "border-positive/30 bg-positive/10 text-positive",
    negative: "border-negative/30 bg-negative/10 text-negative",
    accent: "border-accent/40 bg-accent/10 text-accent-bright",
    warning: "border-warning/30 bg-warning/10 text-warning",
  }[tone];

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-2xs font-medium",
        tones,
        className,
      )}
    >
      {children}
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/* States: loading / empty / error                                            */
/* -------------------------------------------------------------------------- */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded bg-surface-raised",
        "after:absolute after:inset-0 after:animate-shimmer after:bg-gradient-to-r",
        "after:from-transparent after:via-border-strong/40 after:to-transparent",
        className,
      )}
      aria-hidden="true"
    />
  );
}

/** Skeleton rows shaped like the table they stand in for, not one grey block. */
export function TableSkeleton({ rows = 6, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <div className="space-y-px p-1" aria-hidden="true">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex items-center gap-3 px-3 py-2">
          {Array.from({ length: cols }).map((_, c) => (
            <Skeleton
              key={c}
              className={cn("h-3", c === 0 ? "w-28" : "flex-1")}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex h-full flex-col items-center justify-center gap-2 px-6 py-10 text-center",
        className,
      )}
    >
      {Icon && <Icon className="h-5 w-5 text-subtle" aria-hidden="true" />}
      <p className="text-sm font-medium text-foreground">{title}</p>
      <p className="max-w-sm text-xs leading-relaxed text-muted">{description}</p>
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorState({
  title = "Something failed",
  message,
  onRetry,
  retryLabel = "Retry",
  className,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex h-full flex-col items-center justify-center gap-2 px-6 py-10 text-center",
        className,
      )}
    >
      <AlertTriangle className="h-5 w-5 text-negative" aria-hidden="true" />
      <p className="text-sm font-medium text-foreground">{title}</p>
      <p className="max-w-md text-xs leading-relaxed text-muted">{message}</p>
      {onRetry && (
        <Button size="sm" variant="secondary" onClick={onRetry} className="mt-2">
          {retryLabel}
        </Button>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Form controls                                                              */
/* -------------------------------------------------------------------------- */
export function Field({
  label,
  htmlFor,
  hint,
  error,
  children,
  className,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <label htmlFor={htmlFor} className="block text-xs font-medium text-foreground">
        {label}
      </label>
      {children}
      {error ? (
        <p id={`${htmlFor}-error`} className="text-2xs text-negative" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p id={`${htmlFor}-hint`} className="text-2xs leading-relaxed text-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }
>(({ className, invalid, ...props }, ref) => (
  <input
    ref={ref}
    aria-invalid={invalid || undefined}
    className={cn(
      "h-10 w-full rounded-control border bg-background px-3 text-sm text-foreground",
      "placeholder:text-subtle",
      "transition-[border-color] duration-100 ease-enter",
      "hover:border-border-strong",
      "disabled:cursor-not-allowed disabled:opacity-50",
      invalid ? "border-negative" : "border-border",
      className,
    )}
    {...props}
  />
));
Input.displayName = "Input";

export function Toggle({
  checked,
  onChange,
  label,
  disabled,
  id,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  disabled?: boolean;
  id: string;
}) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border",
        "transition-colors duration-100 ease-enter",
        "disabled:pointer-events-none disabled:opacity-50",
        checked
          ? "border-accent-bright bg-accent"
          : "border-border-strong bg-surface-raised",
      )}
    >
      <span
        className={cn(
          "pointer-events-none ml-0.5 inline-block h-4 w-4 rounded-full bg-foreground",
          "transition-transform duration-150 ease-move",
          checked ? "translate-x-5" : "translate-x-0",
        )}
      />
    </button>
  );
}

/* -------------------------------------------------------------------------- */
/* Connection pip                                                             */
/* -------------------------------------------------------------------------- */
export function StatusPip({
  tone,
  pulse,
}: {
  tone: "positive" | "negative" | "warning" | "neutral" | "accent";
  pulse?: boolean;
}) {
  const colour = {
    positive: "bg-positive",
    negative: "bg-negative",
    warning: "bg-warning",
    neutral: "bg-subtle",
    accent: "bg-accent-bright",
  }[tone];

  return (
    <span className="relative inline-flex h-2 w-2 shrink-0" aria-hidden="true">
      {pulse && (
        <span
          className={cn("absolute inline-flex h-full w-full rounded-full opacity-60", colour)}
          style={{ animation: "pulse-ring 1.8s cubic-bezier(0,0,0.2,1) infinite" }}
        />
      )}
      <span className={cn("relative inline-flex h-2 w-2 rounded-full", colour)} />
    </span>
  );
}
