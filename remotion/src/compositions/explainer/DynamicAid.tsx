import React from "react";
import * as Remotion from "remotion";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  interpolateColors,
  random,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { ExplainerTheme } from "../../lib/explainer-types";

/**
 * Runs a GENERATED motion-graphic aid.
 *
 * An `aid` beat is "a concept made visible" — it used to be an mp4 from a paid
 * video model. Now it's a tiny React component authored once by an LLM (see
 * explainer/assets/aidgen.py), compiled to plain JS by the render-service
 * (POST /aid/compile), and shipped INSIDE the render props as `scene.aidCode`.
 *
 * Why evaluate instead of bundling: render-service bundles remotion/src once at
 * startup and the Dockerfile bakes that source into the image, so a per-project
 * component file would mean a multi-minute image rebuild per project. Shipping
 * one evaluator in the static bundle keeps every future aid a pure DATA change
 * (HANDOFF §11 — "keep the scene list data-driven so new shot types don't need a
 * redeploy").
 *
 * The generated code is a PURE FUNCTION of its arguments and must not call
 * hooks: this component owns all hook calls and hands the frame down. That kills
 * a whole class of hook-order crashes and lets /aid/probe render it in isolation.
 */

/** The exact argument object a generated `Aid` receives. Keep in sync with the
 * contract in explainer/assets/aidgen.py — that prompt is the other half. */
export interface AidArgs {
  theme: ExplainerTheme;
  frame: number;
  fps: number;
  durationInFrames: number;
  /** 0 -> 1 across the whole beat. The main thing generated code should animate on. */
  progress: number;
  lib: AidLib;
  props: Record<string, unknown>;
}

export interface AidLib {
  interpolate: typeof interpolate;
  interpolateColors: typeof interpolateColors;
  random: typeof random;
  Easing: typeof Easing;
  /** spring() with fps pre-bound, so generated code never has to thread it. */
  spring: (opts: { frame: number; config?: Record<string, number>; durationInFrames?: number }) => number;
}

type AidFn = (args: AidArgs) => React.ReactNode;

/**
 * Compiled-code -> function cache. Module-level (not useMemo) on purpose: a
 * render re-mounts the React tree per frame, so a hook-local memo would re-run
 * `new Function` thousands of times per short.
 */
const COMPILED = new Map<string, AidFn | null>();

function compile(code: string): AidFn | null {
  const hit = COMPILED.get(code);
  if (hit !== undefined) return hit;

  let fn: AidFn | null = null;
  try {
    // `React` and `Remotion` are in scope for the generated body: esbuild emits
    // classic-runtime `React.createElement` calls, and some aids reach for
    // Remotion.AbsoluteFill. Nothing else is provided — no require, no import,
    // no fetch. The render-service denylist rejects those at compile time.
    const factory = new Function(
      "React",
      "Remotion",
      `${code}\n;return typeof Aid === "function" ? Aid : null;`
    );
    const out = factory(React, Remotion);
    fn = typeof out === "function" ? (out as AidFn) : null;
  } catch (err) {
    console.error("[DynamicAid] evaluation failed:", err);
    fn = null;
  }

  COMPILED.set(code, fn);
  return fn;
}

/** Catches a throw from inside generated code so one bad aid degrades to the
 * fallback visual instead of killing the whole render. */
class AidBoundary extends React.Component<
  { fallback: React.ReactNode; children: React.ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(err: unknown) {
    console.error("[DynamicAid] render threw:", err);
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

const AidRunner: React.FC<{
  fn: AidFn;
  theme: ExplainerTheme;
  props: Record<string, unknown>;
}> = ({ fn, theme, props }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const progress = interpolate(frame, [0, Math.max(1, durationInFrames - 1)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const lib: AidLib = {
    interpolate,
    interpolateColors,
    random,
    Easing,
    spring: (opts) => spring({ fps, ...opts }),
  };

  return <>{fn({ theme, frame, fps, durationInFrames, progress, lib, props })}</>;
};

/**
 * Renders `code` on a branded ground, falling back to `fallback` if the code is
 * missing, fails to evaluate, or throws while rendering.
 */
export const DynamicAid: React.FC<{
  code?: string;
  aidProps?: Record<string, unknown>;
  theme: ExplainerTheme;
  fallback: React.ReactNode;
}> = ({ code, aidProps, theme, fallback }) => {
  const fn = code ? compile(code) : null;
  if (!fn) return <>{fallback}</>;

  return (
    <AidBoundary fallback={fallback}>
      {/* The ground is ours, not the generated code's — an aid that draws only a
          centred figure still sits on brand, and a transparent aid never shows
          black. */}
      <AbsoluteFill style={{ backgroundColor: theme.bg, overflow: "hidden" }}>
        <AidRunner fn={fn} theme={theme} props={aidProps ?? {}} />
      </AbsoluteFill>
    </AidBoundary>
  );
};

export function hasAidCode(scene: { aidCode?: string }): boolean {
  return typeof scene.aidCode === "string" && scene.aidCode.trim().length > 0;
}
