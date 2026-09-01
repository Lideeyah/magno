import type { Config } from "tailwindcss";

/**
 * Tokens mirror brand.md. Every colour used in the product resolves through a
 * CSS variable defined in globals.css, so nothing downstream hardcodes a hex.
 */
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        surface: {
          DEFAULT: "var(--surface)",
          raised: "var(--surface-raised)",
        },
        border: {
          DEFAULT: "var(--border)",
          strong: "var(--border-strong)",
        },
        foreground: "var(--foreground)",
        muted: "var(--muted)",
        subtle: "var(--subtle)",
        accent: {
          DEFAULT: "var(--accent)",
          bright: "var(--accent-bright)",
          dim: "var(--accent-dim)",
        },
        positive: "var(--positive)",
        negative: "var(--negative)",
        warning: "var(--warning)",
        ring: "var(--accent-bright)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: [
          "var(--font-mono)",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "monospace",
        ],
      },
      borderRadius: {
        card: "0.5rem",
        control: "0.375rem",
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      transitionTimingFunction: {
        enter: "cubic-bezier(0, 0, 0.2, 1)",
        exit: "cubic-bezier(0.4, 0, 1, 1)",
        move: "cubic-bezier(0.4, 0, 0.2, 1)",
      },
      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "pulse-ring": {
          "0%": { boxShadow: "0 0 0 0 rgb(59 130 246 / 0.45)" },
          "70%": { boxShadow: "0 0 0 10px rgb(59 130 246 / 0)" },
          "100%": { boxShadow: "0 0 0 0 rgb(59 130 246 / 0)" },
        },
        marquee: {
          from: { transform: "translateX(0)" },
          to: { transform: "translateX(-50%)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "fade-up": "fade-up 150ms cubic-bezier(0, 0, 0.2, 1)",
        "pulse-ring": "pulse-ring 1.8s cubic-bezier(0, 0, 0.2, 1) infinite",
        marquee: "marquee 60s linear infinite",
        shimmer: "shimmer 1.6s infinite",
      },
    },
  },
  plugins: [],
};

export default config;
