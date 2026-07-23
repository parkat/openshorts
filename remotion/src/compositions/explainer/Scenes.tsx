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

// Short-form retention: hard-cut / punch to a new visual about this often.
const BEAT_SEC = 1.0;

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

// Hard-cut punch framings so a held clip keeps "cutting" every beat.
const PUNCHES = [
  { scale: 1.08, x: 0, y: 0 },
  { scale: 1.24, x: -6, y: -4 },
  { scale: 1.14, x: 6, y: 3 },
  { scale: 1.32, x: 0, y: -6 },
];
function punchStyle(beat: number): React.CSSProperties {
  const p = PUNCHES[beat % PUNCHES.length];
  return { transform: `scale(${p.scale}) translate(${p.x}%, ${p.y}%)` };
}

/** Split the shot into beats and render each with a hard cut. Uses the explicit,
 * speech-aligned `beatsMs` (variable 0.75–2.0s cuts from render.py) when provided;
 * otherwise falls back to uniform ~BEAT_SEC beats. */
const Beats: React.FC<{
  beatsMs?: number[];
  children: (beat: number, beatFrames: number) => React.ReactNode;
}> = ({ beatsMs, children }) => {
  const { durationInFrames, fps } = useVideoConfig();
  let lengths: number[];
  if (beatsMs && beatsMs.length) {
    lengths = beatsMs.map((ms) => Math.max(1, Math.round((ms / 1000) * fps)));
  } else {
    const bf = Math.max(1, Math.round(BEAT_SEC * fps));
    const n = Math.max(1, Math.round(durationInFrames / bf));
    lengths = Array.from({ length: n }, () => Math.ceil(durationInFrames / n));
  }
  let from = 0;
  return (
    <>
      {lengths.map((len, b) => {
        const el = (
          <Sequence key={b} from={from} durationInFrames={len} layout="none">
            {children(b, len)}
          </Sequence>
        );
        from += len;
        return el;
      })}
    </>
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

/** Stock b-roll. One clip -> plays continuously (no awkward same-clip skipping);
 * multiple clips -> hard-cut between DISTINCT footage each beat (a real montage). */
const StockVideo: React.FC<{ videos: string[]; beats?: number[] }> = ({ videos, beats }) => {
  if (videos.length <= 1) {
    return (
      <AbsoluteFill style={{ backgroundColor: "#000" }}>
        <VideoClip src={videos[0]} />
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      <Beats beatsMs={beats}>
        {(b) => (
          <AbsoluteFill>
            <VideoClip src={videos[b % videos.length]} />
          </AbsoluteFill>
        )}
      </Beats>
    </AbsoluteFill>
  );
};

/** Generated stills, jump-cut between them with Ken Burns + punch each beat. */
const ImageScene: React.FC<{ images: string[]; beats?: number[] }> = ({ images, beats }) => (
  <AbsoluteFill style={{ backgroundColor: "#000" }}>
    <Beats beatsMs={beats}>
      {(b) => (
        <AbsoluteFill style={punchStyle(b)}>
          <KenBurns src={images[b % images.length]} seed={b + 1} />
        </AbsoluteFill>
      )}
    </Beats>
  </AbsoluteFill>
);

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
export const AccentClipScene: React.FC<SceneProps> = ({ scene, theme }) => (
  <AbsoluteFill style={{ backgroundColor: "#000" }}>
    {scene.videoUrl && (
      <OffthreadVideo
        src={scene.videoUrl}
        muted={scene.duckAudio !== false}
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
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
  const vids = sceneVideos(scene);
  if (vids.length) return <StockVideo videos={vids} beats={scene.beats} />;
  const imgs = sceneImages(scene);
  if (imgs.length) return <ImageScene images={imgs} beats={scene.beats} />;
  if (scene.type === "figure" && (scene.text ?? "").trim())
    return <StatScene scene={scene} theme={theme} />;
  return <AnimatedBackdrop theme={theme} role={scene.role} />;
};
