import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { Router } from "express";
import { z } from "zod";
import * as esbuild from "esbuild";
import { selectComposition, renderStill } from "@remotion/renderer";
import { getBundleLocation } from "./bundle.js";

/**
 * Compile + validate LLM-authored motion-graphic "aid" components.
 *
 * The explainer lane used to buy each aid as an mp4 from a video model. Now the
 * LLM writes a small React component instead (explainer/assets/aidgen.py), and
 * this module is the gate it has to get through before the code is allowed
 * anywhere near a project:
 *
 *   POST /aid/compile  — static denylist, then esbuild TSX -> plain JS
 *   POST /aid/probe    — render it for real and reject blank / non-animating output
 *
 * Compilation is TRANSFORM-ONLY: no bundling, no module resolution. That's what
 * makes `import`/`require` fail loudly instead of silently pulling something in.
 */

export const aidRouter = Router();

const MAX_SOURCE_CHARS = 20000;

/**
 * Patterns rejected before we even try to compile. This is a denylist over
 * generated code we asked for, not a security sandbox — the code still runs in
 * the renderer's Chromium. It exists to catch the LLM reaching for capabilities
 * the contract says it doesn't have.
 */
const FORBIDDEN: { pattern: RegExp; why: string }[] = [
  { pattern: /\bimport\s*[({'"*]/, why: "no imports — React and Remotion are already in scope" },
  { pattern: /\bfrom\s+['"]/, why: "no imports — React and Remotion are already in scope" },
  { pattern: /\brequire\s*\(/, why: "no require()" },
  { pattern: /\bfetch\s*\(/, why: "no network access" },
  { pattern: /\bXMLHttpRequest\b/, why: "no network access" },
  { pattern: /\bWebSocket\b/, why: "no network access" },
  { pattern: /\beval\s*\(/, why: "no eval()" },
  { pattern: /\bFunction\s*\(/, why: "no dynamic Function construction" },
  { pattern: /\bdocument\b/, why: "no direct DOM access — return JSX instead" },
  { pattern: /\bwindow\b/, why: "no window access" },
  { pattern: /\bglobalThis\b/, why: "no globalThis access" },
  { pattern: /\bnavigator\b/, why: "no navigator access" },
  { pattern: /\b(?:local|session)Storage\b/, why: "no storage access" },
  { pattern: /\bprocess\b/, why: "no process access" },
  {
    pattern: /\buse[A-Z]\w*\s*\(/,
    why:
      "no React hooks — Aid must be a pure function of its arguments; use the " +
      "frame/progress/lib values passed in",
  },
];

/**
 * Colour literals break the whole point of the swap: a mood preset re-themes an
 * aid for free ONLY if every colour comes from `theme`. Hex is banned outright.
 *
 * `rgba(...)` is deliberately allowed — it's how you write a theme-neutral scrim
 * or a translucent overlay, and it carries no brand colour of its own.
 *
 * The `[^\w]` tail keeps `url(#gradientId)` style references from matching; ids
 * that happen to be 3/6 hex characters would false-positive, which is an
 * acceptable trade for a rule this load-bearing.
 */
const HEX_COLOUR = /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![0-9a-zA-Z])/;

export interface CompileResult {
  ok: boolean;
  js?: string;
  errors: string[];
}

export function lintAidSource(source: string): string[] {
  const errors: string[] = [];

  if (!source || !source.trim()) {
    errors.push("empty source");
    return errors;
  }
  if (source.length > MAX_SOURCE_CHARS) {
    errors.push(`source too long (${source.length} chars, max ${MAX_SOURCE_CHARS})`);
  }
  if (!/\b(?:const|let|var|function)\s+Aid\b/.test(source)) {
    errors.push("must define a component named exactly `Aid`");
  }
  for (const { pattern, why } of FORBIDDEN) {
    const m = source.match(pattern);
    if (m) errors.push(`forbidden \`${m[0].trim()}\`: ${why}`);
  }
  const hex = source.match(HEX_COLOUR);
  if (hex) {
    errors.push(
      `hardcoded colour \`${hex[0]}\`: every colour must come from theme ` +
        "(theme.bg, theme.ink, theme.rainbow[n], theme.highlight) or the aid " +
        "cannot follow a mood preset"
    );
  }
  return errors;
}

/** Lint, then transform TSX -> plain JS. No bundler, no module resolution. */
export async function compileAid(source: string): Promise<CompileResult> {
  const errors = lintAidSource(source);
  if (errors.length) return { ok: false, errors };

  try {
    const out = await esbuild.transform(source, {
      loader: "tsx",
      // Classic JSX runtime on purpose: the automatic runtime emits an import of
      // "react/jsx-runtime", which has nothing to resolve it here. Classic emits
      // React.createElement, and DynamicAid supplies `React` in scope.
      jsx: "transform",
      jsxFactory: "React.createElement",
      jsxFragment: "React.Fragment",
      format: "cjs",
      target: "es2020",
      logLevel: "silent",
    });

    // esbuild's cjs wrapper would reference `exports`/`module`; we asked for no
    // exports, so anything left referencing them means the model exported.
    if (/\b(?:module\.exports|exports\.)/.test(out.code)) {
      return {
        ok: false,
        errors: ["do not export — just declare `const Aid = (...) => ...`"],
      };
    }

    return { ok: true, js: out.code, errors: [] };
  } catch (err) {
    const e = err as { errors?: { text: string; location?: { line: number } }[] };
    const msgs = e.errors?.length
      ? e.errors.map((x) => (x.location ? `line ${x.location.line}: ${x.text}` : x.text))
      : [err instanceof Error ? err.message : String(err)];
    return { ok: false, errors: msgs };
  }
}

// --- Probe -------------------------------------------------------------------

/**
 * Chromium is expensive and the caller (the assets stage) is single-slot
 * anyway, so probes run one at a time rather than storming the box.
 */
let probeChain: Promise<unknown> = Promise.resolve();
function serialize<T>(fn: () => Promise<T>): Promise<T> {
  const next = probeChain.then(fn, fn);
  probeChain = next.catch(() => undefined);
  return next;
}

const PROBE_SCALE = 0.25; // 1080x1920 layout, rendered at 270x480 — same layout, ~16x less pixels

async function stillBytes(
  serveUrl: string,
  inputProps: Record<string, unknown>,
  frame: number,
  dir: string
): Promise<Buffer> {
  const composition = await selectComposition({
    serveUrl,
    id: "AidProbe",
    inputProps,
  });
  const output = path.join(dir, `probe_${frame}.png`);
  await renderStill({
    composition,
    serveUrl,
    output,
    inputProps,
    frame,
    imageFormat: "png",
    scale: PROBE_SCALE,
  });
  return fs.readFileSync(output);
}

export interface ProbeResult {
  ok: boolean;
  reason?: string;
}

/**
 * Render the aid for real and check it actually draws something that moves.
 *
 * Blankness is decided by comparing against a CONTROL frame rendered with no
 * code at all (which paints the bare themed ground). Byte-identical to the
 * control means the aid painted nothing — or threw and hit DynamicAid's
 * fallback. Either way it's not usable, and this catches both without needing
 * an image decoder.
 */
export async function probeAid(
  js: string,
  theme: Record<string, unknown>,
  aidProps: Record<string, unknown>,
  durationInFrames: number
): Promise<ProbeResult> {
  const serveUrl = getBundleLocation();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), `aidprobe-${randomUUID().slice(0, 8)}-`));

  const base = {
    theme,
    aidProps,
    durationInFrames,
    fps: 30,
    width: 1080,
    height: 1920,
  };

  try {
    const last = Math.max(1, durationInFrames - 1);
    const frames = [Math.round(last * 0.1), Math.round(last * 0.5), last];

    const control = await stillBytes(serveUrl, { ...base, aidCode: "" }, frames[0], dir);

    const shots: Buffer[] = [];
    for (const f of frames) {
      shots.push(await stillBytes(serveUrl, { ...base, aidCode: js }, f, dir));
    }

    if (shots.some((b) => b.equals(control))) {
      return {
        ok: false,
        reason:
          "renders nothing — at least one frame is identical to an empty themed " +
          "background. The component must draw visible shapes.",
      };
    }
    if (shots[0].equals(shots[1]) && shots[1].equals(shots[2])) {
      return {
        ok: false,
        reason:
          "does not animate — the first, middle and last frames are identical. " +
          "Drive geometry from `progress` (0->1) or `frame`.",
      };
    }
    return { ok: true };
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

// --- Routes ------------------------------------------------------------------

const compileSchema = z.object({ source: z.string() });

const probeSchema = z.object({
  js: z.string().min(1),
  theme: z.record(z.string(), z.unknown()),
  aidProps: z.record(z.string(), z.unknown()).optional(),
  durationInFrames: z.number().int().positive().max(3600).optional(),
});

aidRouter.post("/aid/compile", async (req, res) => {
  const parsed = compileSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ ok: false, errors: ["invalid request body"] });
    return;
  }
  const result = await compileAid(parsed.data.source);
  res.json(result);
});

aidRouter.post("/aid/probe", async (req, res) => {
  const parsed = probeSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ ok: false, reason: "invalid request body" });
    return;
  }
  const { js, theme, aidProps, durationInFrames } = parsed.data;
  try {
    const result = await serialize(() =>
      probeAid(js, theme, aidProps ?? {}, durationInFrames ?? 120)
    );
    res.json(result);
  } catch (err) {
    // A throw here is a probe-infrastructure failure, not a verdict on the code.
    // Say so, so the caller doesn't burn a retry rewriting a fine component.
    res.status(500).json({
      ok: false,
      reason: `probe failed to run: ${err instanceof Error ? err.message : String(err)}`,
      infrastructure: true,
    });
  }
});
