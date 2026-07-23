import { z } from "zod";
import { captionWordSchema, type CaptionWord } from "./types";

/**
 * Data-driven scene list for the "Scientific Awareness" explainer lane.
 *
 * Everything the ExplainerShort composition needs comes in as props so new shot
 * types / brand tweaks never require a redeploy (HANDOFF §3, §11). Scene timing is
 * in ms (from `explainer/align.py`); the composition converts to frames with fps.
 */

export type ExplainerSceneType =
  | "slide"
  | "motion_text"
  | "figure"
  | "accent_clip"
  | "broll";

export interface ExplainerScene {
  type: ExplainerSceneType;
  startMs: number;
  endMs: number;
  role?: string; // hook | setup | thing | why | button
  text?: string; // headline for slide / motion_text
  imageUrl?: string; // single figure / slide background (served over http)
  images?: string[]; // multiple stills -> hard jump-cuts between them within the shot
  videoUrl?: string; // accent_clip / broll source
  attribution?: string; // "via <source>" overlay while an accent clip plays
  duckAudio?: boolean; // accent clip: mute/duck its own audio under narration
}

// 80s retro-TV / VHS palette + fonts, sourced from explainer/brand.py.
export interface ExplainerTheme {
  bg: string;
  ink: string;
  rainbow: string[]; // red..purple accent ramp
  displayFont: string;
  captionFont: string;
  highlight: string;
  vhs: boolean; // scanlines / grain / chroma wobble
}

export interface ExplainerShortProps {
  durationInFrames: number;
  fps: number;
  width: number;
  height: number;
  narrationUrl: string; // spoken track (WAV/MP3) over the whole short
  musicUrl: string | null; // ducked CC0 bed, optional
  captions: CaptionWord[]; // word-level, rides the narration audio
  scenes: ExplainerScene[]; // per-shot visuals
  theme: ExplainerTheme;
}

export const DEFAULT_THEME: ExplainerTheme = {
  bg: "#F3ECD9",
  ink: "#2E2A26",
  rainbow: ["#C1544A", "#D98A45", "#E3C05A", "#5F9E9A", "#5A7BA6", "#8A6BA1"],
  // Concrete, always-present CSS stacks (headless Chromium has no Futura/Eurostile).
  displayFont: '"Arial Black", "Helvetica Neue", Arial, sans-serif',
  captionFont: '"Arial Black", Impact, "Helvetica Neue", sans-serif',
  highlight: "#E3C05A",
  vhs: true,
};

// --- Zod (render-service validation) ---
export const explainerSceneSchema = z.object({
  type: z.enum(["slide", "motion_text", "figure", "accent_clip", "broll"]),
  startMs: z.number().min(0),
  endMs: z.number().min(0),
  role: z.string().optional(),
  text: z.string().optional(),
  imageUrl: z.string().optional(),
  images: z.array(z.string()).optional(),
  videoUrl: z.string().optional(),
  attribution: z.string().optional(),
  duckAudio: z.boolean().optional(),
});

export const explainerThemeSchema = z.object({
  bg: z.string(),
  ink: z.string(),
  rainbow: z.array(z.string()),
  displayFont: z.string(),
  captionFont: z.string(),
  highlight: z.string(),
  vhs: z.boolean(),
});

export const explainerShortPropsSchema = z.object({
  durationInFrames: z.number().int().positive(),
  fps: z.number().positive(),
  width: z.number().int().positive(),
  height: z.number().int().positive(),
  narrationUrl: z.string(),
  musicUrl: z.string().nullable(),
  captions: z.array(captionWordSchema),
  scenes: z.array(explainerSceneSchema),
  theme: explainerThemeSchema,
});
