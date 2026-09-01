import * as React from "react";

import { cn } from "@/lib/format";

/**
 * Inline glossary. Options vocabulary is the main thing standing between a
 * capable reader and understanding what Magno does, so every term of art gets
 * its definition attached where it is first used rather than in a glossary
 * nobody scrolls to.
 *
 * Rendered as <abbr>, which carries the definition to screen readers and to
 * hover without any JavaScript.
 */
export function Term({
  children,
  define,
  className,
}: {
  children: React.ReactNode;
  define: string;
  className?: string;
}) {
  return (
    <abbr
      title={define}
      className={cn(
        "cursor-help border-b border-dotted border-subtle text-foreground no-underline",
        className,
      )}
    >
      {children}
    </abbr>
  );
}
