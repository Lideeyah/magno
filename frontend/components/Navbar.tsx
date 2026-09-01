"use client";

import { Github } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { cn } from "@/lib/format";
import { GITHUB_URL } from "@/lib/site";

import { ScrollProgress } from "./ScrollProgress";

export function MagnoMark({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      {/* A horseshoe magnet with its field converging on zero — the product in
          one glyph: opposing poles pulling exposure back to the centre line. */}
      <svg viewBox="0 0 24 24" className="h-[18px] w-[18px] shrink-0" fill="none" aria-hidden="true">
        <path
          d="M5 20V11a7 7 0 0 1 14 0v9"
          stroke="var(--accent-bright)"
          strokeWidth="2.25"
          strokeLinecap="round"
        />
        <path d="M5 20h4M15 20h4" stroke="#FFFFFF" strokeWidth="2.25" strokeLinecap="round" />
        <path d="M12 4v6" stroke="var(--subtle)" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      <span className="num text-sm font-bold tracking-tight text-white">Magno</span>
    </span>
  );
}

const NAV = [
  { href: "#mechanics", label: "Mechanics" },
  { href: "#architecture", label: "Architecture" },
  { href: "#simulator", label: "Shock Simulator" },
];

export function Navbar({ cta, className }: { cta?: React.ReactNode; className?: string }) {
  return (
    <header className={cn("fixed inset-x-0 top-0 z-50", className)}>
      <div className="border-b border-transparent bg-background/70 backdrop-blur-md">
        <nav className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-4 px-4 md:px-6 lg:px-8">
          <Link href="/" className="rounded-md transition-opacity duration-100 hover:opacity-80">
            <MagnoMark />
            <span className="sr-only">Magno home</span>
          </Link>

          <div className="hidden items-center gap-1 md:flex">
            {NAV.map((item) => (
              <a
                key={item.href}
                href={item.href}
                className={cn(
                  "rounded-md px-3 py-1.5 text-xs font-medium text-muted",
                  "transition-colors duration-100 hover:text-white",
                )}
              >
                {item.label}
              </a>
            ))}
          </div>

          <div className="flex items-center gap-1">
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noreferrer noopener"
              aria-label="Magno on GitHub"
              className={cn(
                "flex h-10 w-10 items-center justify-center rounded-md text-muted",
                "transition-colors duration-100 hover:bg-white/[0.06] hover:text-white",
              )}
            >
              <Github className="h-4 w-4" aria-hidden="true" />
            </a>
            {cta ?? (
              <Link
                href="/terminal"
                className={cn(
                  "inline-flex h-9 items-center rounded-md bg-accent px-3.5 text-xs font-medium text-white",
                  "transition-colors duration-100 hover:bg-accent-bright active:translate-y-px",
                )}
              >
                Launch Terminal
              </Link>
            )}
          </div>
        </nav>
      </div>
      {/* Hairline that fades out at both edges rather than butting into the
          viewport — the border reads as part of the page, not a boxed bar. */}
      <div
        className="h-px w-full bg-gradient-to-r from-transparent via-white/[0.10] to-transparent"
        aria-hidden="true"
      />
      <ScrollProgress />
    </header>
  );
}
