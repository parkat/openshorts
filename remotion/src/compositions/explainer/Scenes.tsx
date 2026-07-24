import React from "react";
import {
  AbsoluteFill,
  Img,
  OffthreadVideo,
  Sequence,
  interpolate,
  random,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { ExplainerScene, ExplainerTheme } from "../../lib/explainer-types";
import { SvgScene, hasSvg } from "./SvgGraphics";

interface SceneProps {
  scene: ExplainerScene;
  theme: ExplainerTheme;
}

function useEntrance(): number {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame, fps, config: { mass: 0.5, stiffness: 140, damping: 14 } });
}

function pickAccent(theme: ExplainerTheme, role?: string): string {
  const order = ["hook", "setup", "thing", "why", "button", "escalate"];
  const i = role ? order.indexOf(role) : -1;
  return theme.rainbow[(i >= 0 ? i : 0) % theme.rainbow.length] ?? theme.rainbow[0];
}

/** Play N layers in order, each for an equal slice of the shot — natural pacing,
 * one visual per beat, NO rapid sub-cutting. A single-layer shot just holds. */
const Sequential: React.FC<{ count: number; render: (i: number) => React.ReactNode }> = ({
  count,
  render,
}) => {
  const { durationInFrames } = useVideoConfig();
  const n = Math.max(1, count);
  const each = Math.max(1, Math.ceil(durationInFrames / n));
  let from = 0;
  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {Array.from({ length: n }).map((_, i) => {
        const el = (
          <Sequence key={i} from={from} durationInFrames={each} layout="none">
            <AbsoluteFill>{render(i)}</AbsoluteFill>
          </Sequence>
        );
        from += each;
        return el;
      })}
    </AbsoluteFill>
  );
};

/** Ken Burns pan/zoom on a still. */
const KenBurns: React.FC<{ src: string; seed: number }> = ({ src, seed }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const t = interpolate(frame, [0, Math.max(1, durationInFrames)], [0, 1], {
    extrapolateRight: "clamp",
  });
  const zoomIn = random(`z${seed}`) > 0.5;
  const scale = zoomIn ? 1.06 + 0.14 * t : 1.2 - 0.14 * t;
  const panX = (random(`x${seed}`) - 0.5) * 6 * t;
  const panY = (random(`y${seed}`) - 0.5) * 6 * t;
  return (
    <Img
      src={src}
      style={{
        width: "100%",
        height: "100%",
        objectFit: "cover",
        transform: `scale(${scale}) translate(${panX}%, ${panY}%)`,
      }}
    />
  );
};

function sceneImages(scene: ExplainerScene): string[] {
  if (scene.images && scene.images.length) return scene.images;
  if (scene.imageUrl) return [scene.imageUrl];
  return [];
}

function sceneVideos(scene: ExplainerScene): string[] {
  if (scene.videos && scene.videos.length) return scene.videos;
  if (scene.videoUrl) return [scene.videoUrl];
  return [];
}

/** One stock clip, full-bleed with a gentle push-in (natural footage motion). */
const VideoClip: React.FC<{ src: string }> = ({ src }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const t = interpolate(frame, [0, Math.max(1, durationInFrames)], [0, 1], {
    extrapolateRight: "clamp",
  });
  return (
    <OffthreadVideo
      src={src}
      muted
      style={{
        width: "100%",
        height: "100%",
        objectFit: "cover",
        transform: `scale(${1.04 + 0.1 * t})`,
      }}
    />
  );
};

/** Stock b-roll. One clip -> holds continuously. Multiple clips -> each plays in
 * order for an equal slice of the shot (a calm montage, natural pace — no fast cuts). */
const StockVideo: React.FC<{ videos: string[] }> = ({ videos }) => {
  if (videos.length <= 1) {
    return (
      <AbsoluteFill style={{ backgroundColor: "#000" }}>
        <VideoClip src={videos[0]} />
      </AbsoluteFill>
    );
  }
  return <Sequential count={videos.length} render={(i) => <VideoClip src={videos[i]} />} />;
};

/** Generated explanatory AID clips — staged clips play in sequence (progression),
 * each an equal slice; muted (audio is the narrator or the speaker's soundbite). */
const AidSequence: React.FC<{ videos: string[] }> = ({ videos }) => (
  <Sequential count={videos.length} render={(i) => <VideoClip src={videos[i]} />} />
);

/** Generated stills — hold with a gentle Ken Burns pan/zoom; multiple stills play
 * in sequence (equal slices). No punch, no rapid cutting. */
const ImageScene: React.FC<{ images: string[] }> = ({ images }) => {
  if (images.length <= 1) {
    return (
      <AbsoluteFill style={{ backgroundColor: "#000" }}>
        <KenBurns src={images[0]} seed={1} />
      </AbsoluteFill>
    );
  }
  return (
    <Sequential count={images.length} render={(i) => <KenBurns src={images[i]} seed={i + 1} />} />
  );
};

/** Animated brand backdrop for text beats — NO headline (the captions ARE the
 * words, so nothing competes with them). Continuous motion + a focal pulse, base
 * color alternates by role so consecutive text beats read as distinct cuts. */
const AnimatedBackdrop: React.FC<{ theme: ExplainerTheme; role?: string }> = ({
  theme,
  role,
}) => {
  const frame = useCurrentFrame();
  const accent = pickAccent(theme, role);
  const onAccent = !!role && ["hook", "thing", "why", "escalate"].includes(role);
  const base = onAccent ? accent : theme.bg;
  const fg = onAccent ? theme.bg : theme.ink;
  return (
    <AbsoluteFill style={{ backgroundColor: base, overflow: "hidden" }}>
      <div
        style={{
          position: "absolute",
          inset: "-30%",
          background: `repeating-linear-gradient(120deg, ${theme.rainbow.join(", ")})`,
          opacity: onAccent ? 0.16 : 0.1,
          transform: `translateX(${((frame * 1.4) % 260) - 130}px) rotate(6deg)`,
        }}
      />
      {theme.rainbow.map((c, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            width: 210,
            height: 210,
            borderRadius: "50%",
            background: c,
            opacity: 0.14,
            mixBlendMode: onAccent ? "screen" : "multiply",
            left: `${((i * 29 + frame * 0.25) % 130) - 15}%`,
            top: `${14 + i * 11 + Math.sin(frame / 28 + i) * 5}%`,
          }}
        />
      ))}
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
        {[0, 1, 2].map((k) => (
          <div
            key={k}
            style={{
              position: "absolute",
              width: 240 + k * 150,
              height: 240 + k * 150,
              borderRadius: "50%",
              border: `10px solid ${fg}`,
              opacity: 0.12 - k * 0.03,
              transform: `scale(${0.9 + 0.1 * Math.sin(frame / 18 + k)})`,
            }}
          />
        ))}
        <div
          style={{
            width: 120,
            height: 120,
            borderRadius: "50%",
            background: accent,
            border: `8px solid ${fg}`,
            transform: `scale(${0.9 + 0.13 * Math.sin(frame / 12)})`,
          }}
        />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/** A single big STAT (a number/short label) — a highlight, not prose, so it
 * reinforces rather than competes with the captions. */
export const StatScene: React.FC<SceneProps> = ({ scene, theme }) => {
  const e = useEntrance();
  const frame = useCurrentFrame();
  const text = scene.text ?? "";
  const size = text.length > 8 ? 96 : text.length > 4 ? 140 : 200;
  return (
    <AbsoluteFill
      style={{
        backgroundColor: theme.bg,
        justifyContent: "center",
        alignItems: "center",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          position: "absolute",
          width: 560,
          height: 560,
          borderRadius: "50%",
          background: pickAccent(theme, scene.role),
          opacity: 0.16,
          transform: `scale(${1 + 0.06 * Math.sin(frame / 15)})`,
        }}
      />
      <div
        style={{
          transform: `scale(${interpolate(e, [0, 1], [0.6, 1])})`,
          opacity: e,
          textAlign: "center",
          padding: "0 60px",
          fontFamily: theme.displayFont,
          fontSize: size,
          fontWeight: 900,
          letterSpacing: "-0.02em",
          lineHeight: 1,
          color: theme.ink,
          textTransform: "uppercase",
        }}
      >
        {text}
      </div>
    </AbsoluteFill>
  );
};

/** User-supplied accent clip (talking head). Continuous — NOT beat-cut, so the
 * speaker isn't chopped. Shows "via <source>". */
export const AccentClipScene: React.FC<SceneProps> = ({ scene, theme }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const t = interpolate(frame, [0, Math.max(1, durationInFrames)], [0, 1], {
    extrapolateRight: "clamp",
  });
  return (
  <AbsoluteFill style={{ backgroundColor: "#000" }}>
    {scene.videoUrl && (
      <OffthreadVideo
        src={scene.videoUrl}
        muted
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: `scale(${1.03 + 0.09 * t})`,  // slow push-in so a held soundbite isn't static
        }}
      />
    )}
    {scene.attribution && (
      <div
        style={{
          position: "absolute",
          left: 28,
          top: 36,
          padding: "8px 16px",
          borderRadius: 8,
          backgroundColor: "rgba(46,42,38,0.72)",
          color: theme.bg,
          fontFamily: theme.captionFont,
          fontSize: 30,
          letterSpacing: "0.02em",
        }}
      >
        {scene.attribution}
      </div>
    )}
  </AbsoluteFill>
  );
};

/** Dispatch a scene to its renderer. Captions (global layer) always carry the
 * spoken words; scenes are visuals only (footage, animated backdrop, or a stat). */
export const SceneRenderer: React.FC<SceneProps> = ({ scene, theme }) => {
  // Accent talking-head: single clip, continuous (never chop the speaker).
  if (scene.type === "accent_clip") {
    return scene.videoUrl ? (
      <AccentClipScene scene={scene} theme={theme} />
    ) : (
      <AnimatedBackdrop theme={theme} role={scene.role} />
    );
  }
  // Generated aid animation: staged clips play in sequence (progression), not cycled.
  if (scene.type === "aid") {
    const av = sceneVideos(scene);
    if (av.length) return <AidSequence videos={av} />;
  }
  const vids = sceneVideos(scene);
  if (vids.length) return <StockVideo videos={vids} />;
  const imgs = sceneImages(scene);
  if (imgs.length) return <ImageScene images={imgs} />;
  // No on-screen headline/stat text anywhere — the yellow captions are the ONLY
  // text. A text/figure beat shows an animated SVG graphic if one was assigned,
  // else the animated brand backdrop.
  if (hasSvg(scene)) return <SvgScene scene={scene} theme={theme} />;
  return <AnimatedBackdrop theme={theme} role={scene.role} />;
};
