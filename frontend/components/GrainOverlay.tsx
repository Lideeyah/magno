/**
 * Static film-grain texture over the page ground.
 *
 * Flat dark surfaces read as cheap on large displays — subtle luminance noise
 * gives them a matte, physical quality and also breaks up gradient banding.
 * Rendered once as an inline SVG data URI rather than an animated filter: it
 * costs a single tiny background image, never repaints, and has no motion to
 * disable under `prefers-reduced-motion`.
 */
const NOISE = `data:image/svg+xml;utf8,${encodeURIComponent(
  `<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">
     <filter id="n">
       <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="3" stitchTiles="stitch"/>
       <feColorMatrix type="saturate" values="0"/>
     </filter>
     <rect width="200" height="200" filter="url(#n)" opacity="0.42"/>
   </svg>`,
)}`;

export function GrainOverlay() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 z-0 opacity-[0.035] mix-blend-overlay"
      style={{ backgroundImage: `url("${NOISE}")`, backgroundRepeat: "repeat" }}
    />
  );
}
