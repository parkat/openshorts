import React from "react";
import { AbsoluteFill, interpolate, random, useCurrentFrame } from "remotion";

/**
 * Tasteful 80s-VHS treatment layered over the whole short: scanlines, a faint
 * animated grain, and a subtle chroma wobble at the edges. Kept low-opacity so it
 * reads as texture, not a gimmick (brand.vhs). Deterministic via Remotion's
 * seeded random() so every render frame is identical.
 */
export const VhsOverlay: React.FC = () => {
  const frame = useCurrentFrame();
  // Slow horizontal chroma wobble.
  const wobble = interpolate(Math.sin(frame / 14), [-1, 1], [-2.5, 2.5]);
  // Grain drifts each frame but stays seeded/deterministic.
  const grainShift = random(`grain-${frame % 12}`) * 100;

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {/* Chroma-split fringe */}
      <AbsoluteFill
        style={{
          boxShadow: `inset ${wobble}px 0 0 rgba(255,0,80,0.05), inset ${-wobble}px 0 0 rgba(0,180,255,0.05)`,
          mixBlendMode: "screen",
        }}
      />
      {/* Scanlines */}
      <AbsoluteFill
        style={{
          backgroundImage:
            "repeating-linear-gradient(0deg, rgba(0,0,0,0.10) 0px, rgba(0,0,0,0.10) 1px, transparent 2px, transparent 4px)",
          opacity: 0.5,
        }}
      />
      {/* Animated grain */}
      <AbsoluteFill
        style={{
          backgroundImage:
            "repeating-radial-gradient(circle at 30% 40%, rgba(255,255,255,0.03) 0, rgba(0,0,0,0.03) 1px)",
          backgroundPosition: `${grainShift}px ${grainShift}px`,
          opacity: 0.35,
          mixBlendMode: "overlay",
        }}
      />
      {/* Vignette for tube-TV falloff */}
      <AbsoluteFill
        style={{
          background:
            "radial-gradient(ellipse at center, transparent 55%, rgba(0,0,0,0.28) 100%)",
        }}
      />
    </AbsoluteFill>
  );
};
