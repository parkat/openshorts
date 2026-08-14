import React from "react";
import { Composition } from "remotion";
import { ShortVideo } from "./compositions/ShortVideo";
import { ExplainerShort } from "./compositions/ExplainerShort";
import {
  AidProbe,
  DEFAULT_AID_PROBE_PROPS,
  aidProbePropsSchema,
  type AidProbeProps,
} from "./compositions/explainer/AidProbe";
import type { ShortVideoProps } from "./lib/types";
import { shortVideoPropsSchema } from "./lib/types";
import type { ExplainerShortProps } from "./lib/explainer-types";
import {
  DEFAULT_THEME,
  explainerShortPropsSchema,
} from "./lib/explainer-types";

const DEFAULT_PROPS: ShortVideoProps = {
  videoUrl: "",
  durationInFrames: 900, // 30s at 30fps
  fps: 30,
  width: 1080,
  height: 1920,
  subtitles: {
    captions: [
      { text: "This", startMs: 0, endMs: 400 },
      { text: "is", startMs: 400, endMs: 600 },
      { text: "a", startMs: 600, endMs: 750 },
      { text: "demo", startMs: 750, endMs: 1200 },
      { text: "of", startMs: 1200, endMs: 1400 },
      { text: "animated", startMs: 1400, endMs: 2000 },
      { text: "subtitles", startMs: 2000, endMs: 2800 },
      { text: "in", startMs: 2800, endMs: 3000 },
      { text: "Remotion", startMs: 3000, endMs: 3800 },
      { text: "with", startMs: 4000, endMs: 4300 },
      { text: "word", startMs: 4300, endMs: 4700 },
      { text: "level", startMs: 4700, endMs: 5100 },
      { text: "highlighting", startMs: 5100, endMs: 6000 },
    ],
    position: "bottom",
    style: {
      fontFamily: "Arial",
      fontSize: 52,
      fontColor: "#FFFFFF",
      highlightColor: "#FFDD00",
      borderColor: "#000000",
      borderWidth: 3,
      bgColor: "#000000",
      bgOpacity: 0,
      animation: "pop",
    },
  },
  hook: {
    text: "POV: You just discovered OpenShorts",
    position: "top",
    size: "M",
    entranceAnimation: "spring",
    displayDurationSec: 5,
  },
  effects: {
    segments: [
      {
        startSec: 2,
        endSec: 5,
        zoom: 1.2,
        zoomCenterX: 0.5,
        zoomCenterY: 0.35,
        brightness: 1.05,
        contrast: 1.1,
        saturate: 1.15,
      },
      {
        startSec: 8,
        endSec: 12,
        zoom: 1.15,
        zoomCenterX: 0.5,
        zoomCenterY: 0.4,
        brightness: 1,
        contrast: 1,
        saturate: 1,
      },
    ],
  },
};

const DEFAULT_EXPLAINER_PROPS: ExplainerShortProps = {
  durationInFrames: 900, // 30s @ 30fps; real value from calculateMetadata
  fps: 30,
  width: 1080,
  height: 1920,
  narrationUrl: "",
  musicUrl: null,
  captions: [
    { text: "This", startMs: 0, endMs: 400 },
    { text: "changes", startMs: 400, endMs: 900 },
    { text: "everything", startMs: 900, endMs: 1600 },
  ],
  scenes: [
    {
      type: "slide",
      role: "hook",
      startMs: 0,
      endMs: 1600,
      text: "This changes everything",
    },
    {
      type: "motion_text",
      role: "why",
      startMs: 1600,
      endMs: 3200,
      text: "and nobody noticed",
    },
  ],
  theme: DEFAULT_THEME,
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="ExplainerShort"
        schema={explainerShortPropsSchema}
        component={ExplainerShort}
        durationInFrames={DEFAULT_EXPLAINER_PROPS.durationInFrames}
        fps={DEFAULT_EXPLAINER_PROPS.fps}
        width={DEFAULT_EXPLAINER_PROPS.width}
        height={DEFAULT_EXPLAINER_PROPS.height}
        defaultProps={DEFAULT_EXPLAINER_PROPS}
        // Duration follows the scene list / narration length rather than the 30s
        // default, so the short is exactly as long as its audio.
        calculateMetadata={({ props }) => {
          const p = props as unknown as ExplainerShortProps;
          const pos = (v: number | undefined, fallback: number) =>
            typeof v === "number" && v > 0 ? v : fallback;
          const fps = pos(p.fps, DEFAULT_EXPLAINER_PROPS.fps);
          const lastMs = (p.scenes ?? []).reduce(
            (m, s) => Math.max(m, s.endMs || 0),
            0
          );
          const framesFromScenes = Math.round((lastMs / 1000) * fps);
          return {
            durationInFrames:
              framesFromScenes > 0
                ? framesFromScenes
                : Math.round(
                    pos(
                      p.durationInFrames,
                      DEFAULT_EXPLAINER_PROPS.durationInFrames
                    )
                  ),
            fps,
            width: Math.round(pos(p.width, DEFAULT_EXPLAINER_PROPS.width)),
            height: Math.round(pos(p.height, DEFAULT_EXPLAINER_PROPS.height)),
          };
        }}
      />
      {/* Validation harness for a single generated aid — driven by
          POST /aid/probe in the render-service, and handy in Studio for
          eyeballing one aid without rebuilding a whole short. */}
      <Composition
        id="AidProbe"
        schema={aidProbePropsSchema}
        component={AidProbe}
        durationInFrames={DEFAULT_AID_PROBE_PROPS.durationInFrames}
        fps={DEFAULT_AID_PROBE_PROPS.fps}
        width={DEFAULT_AID_PROBE_PROPS.width}
        height={DEFAULT_AID_PROBE_PROPS.height}
        defaultProps={DEFAULT_AID_PROBE_PROPS}
        calculateMetadata={({ props }) => {
          const p = props as unknown as AidProbeProps;
          const pos = (v: number | undefined, fallback: number) =>
            typeof v === "number" && v > 0 ? v : fallback;
          return {
            durationInFrames: Math.round(
              pos(p.durationInFrames, DEFAULT_AID_PROBE_PROPS.durationInFrames)
            ),
            fps: pos(p.fps, DEFAULT_AID_PROBE_PROPS.fps),
            width: Math.round(pos(p.width, DEFAULT_AID_PROBE_PROPS.width)),
            height: Math.round(pos(p.height, DEFAULT_AID_PROBE_PROPS.height)),
          };
        }}
      />
      <Composition
        id="ShortVideo"
        schema={shortVideoPropsSchema}
        component={ShortVideo}
        durationInFrames={DEFAULT_PROPS.durationInFrames}
        fps={DEFAULT_PROPS.fps}
        width={DEFAULT_PROPS.width}
        height={DEFAULT_PROPS.height}
        defaultProps={DEFAULT_PROPS}
        // Derive real duration/dimensions from the render request instead of the
        // hardcoded 30s/1080x1920 defaults, so a rendered short matches the actual
        // clip length (no trailing frozen frame, no 30s truncation).
        calculateMetadata={({ props }) => {
          const p = props as unknown as ShortVideoProps;
          const pos = (v: number | undefined, fallback: number) =>
            typeof v === "number" && v > 0 ? v : fallback;
          return {
            durationInFrames: Math.round(
              pos(p.durationInFrames, DEFAULT_PROPS.durationInFrames)
            ),
            fps: pos(p.fps, DEFAULT_PROPS.fps),
            width: Math.round(pos(p.width, DEFAULT_PROPS.width)),
            height: Math.round(pos(p.height, DEFAULT_PROPS.height)),
          };
        }}
      />
    </>
  );
};
