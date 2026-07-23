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

// Short-form retention: hard-cut to a new visual roughly this often.
const BEAT_SEC = 1.8;

/** Ken Burns pan/zoom on a still — constant slow motion so nothing sits static.
 * Direction/scale vary by seed so consecutive beats don't move identically. */
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

/** Split a shot's image(s) into ~BEAT_SEC hard-cut beats, cycling the images so a
 * longer shot keeps cutting (jump-cut energy) instead of holding one frame. */
const ImageBeats: React.FC<{ images: string[]; theme: ExplainerTheme }> = ({
  images,
}) => {
  const { durationInFrames, fps } = useVideoConfig();
  const beatFrames = Math.max(1, Math.round(BEAT_SEC * fps));
  const nBeats = Math.max(1, Math.round(durationInFrames / beatFrames));
  const each = Math.ceil(durationInFrames / nBeats);
  return (
    <>
      {Array.from({ length: nBeats }).map((_, b) => (
        <Sequence key={b} from={b * each} durationInFrames={each} layout="none">
          <AbsoluteFill>
            <KenBurns src={images[b % images.length]} seed={b + 1} />
          </AbsoluteFill>
        </Sequence>
      ))}
    </>
  );
};

function sceneImages(scene: ExplainerScene): string[] {
  if (scene.images && scene.images.length) return scene.images;
  if (scene.imageUrl) return [scene.imageUrl];
  return [];
}

/**
 * Scene renderers for ExplainerShort. Each takes a scene + theme and fills the
 * frame; the parent <Sequence> handles when it's on screen. Kept data-driven so
 * new shot types slot in without a redeploy.
 */

interface SceneProps {
  scene: ExplainerScene;
  theme: ExplainerTheme;
}

// A gentle spring the retro scenes share for entrances (0 -> 1 over ~0.4s).
function useEntrance(): number {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame, fps, config: { mass: 0.6, stiffness: 120, damping: 16 } });
}

function pickAccent(theme: ExplainerTheme, role?: string): string {
  const order = ["hook", "setup", "thing", "why", "button"];
  const i = role ? order.indexOf(role) : -1;
  const idx = i >= 0 ? i % theme.rainbow.length : 0;
  return theme.rainbow[idx] ?? theme.rainbow[0];
}

/** Full-bleed cover media (figure image / broll / accent video). */
const CoverMedia: React.FC<{ scene: ExplainerScene; kind: "img" | "video" }> = ({
  scene,
  kind,
}) => {
  const src = kind === "img" ? scene.imageUrl : scene.videoUrl;
  if (!src) return null;
  const style: React.CSSProperties = {
    width: "100%",
    height: "100%",
    objectFit: "cover",
  };
  return kind === "img" ? (
    <Img src={src} style={style} />
  ) : (
    <OffthreadVideo src={src} style={style} muted={scene.duckAudio !== false} />
  );
};

/** Retro title card: cream field, rainbow rule, big geometric headline. */
export const SlideScene: React.FC<SceneProps> = ({ scene, theme }) => {
  const e = useEntrance();
  const accent = pickAccent(theme, scene.role);
  const translate = interpolate(e, [0, 1], [40, 0]);
  return (
    <AbsoluteFill
      style={{
        backgroundColor: theme.bg,
        justifyContent: "center",
        alignItems: "center",
        padding: "0 90px",
      }}
    >
      <div
        style={{
          transform: `translateY(${translate}px)`,
          opacity: e,
          textAlign: "center",
        }}
      >
        <div
          style={{
            width: 120,
            height: 12,
            margin: "0 auto 44px",
            borderRadius: 6,
            background: `linear-gradient(90deg, ${theme.rainbow.join(", ")})`,
          }}
        />
        <div
          style={{
            fontFamily: theme.displayFont,
            fontSize: 96,
            lineHeight: 1.04,
            fontWeight: 900,
            letterSpacing: "-0.01em",
            textTransform: "uppercase",
            color: theme.ink,
          }}
        >
          {scene.text}
        </div>
        <div
          style={{
            marginTop: 40,
            width: 70,
            height: 70,
            marginLeft: "auto",
            marginRight: "auto",
            borderRadius: "50%",
            background: accent,
            opacity: 0.9,
          }}
        />
      </div>
    </AbsoluteFill>
  );
};

/** Kinetic type: words punch up on a solid accent field. */
export const MotionTextScene: React.FC<SceneProps> = ({ scene, theme }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const accent = pickAccent(theme, scene.role);
  const words = (scene.text ?? "").split(/\s+/).filter(Boolean);
  return (
    <AbsoluteFill
      style={{
        backgroundColor: accent,
        justifyContent: "center",
        alignItems: "center",
        padding: "0 80px",
      }}
    >
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          gap: "10px 22px",
          maxWidth: "90%",
        }}
      >
        {words.map((w, i) => {
          const appear = spring({
            frame: frame - i * 3,
            fps,
            config: { mass: 0.4, stiffness: 220, damping: 14 },
          });
          return (
            <span
              key={i}
              style={{
                fontFamily: theme.displayFont,
                fontSize: 84,
                fontWeight: 900,
                textTransform: "uppercase",
                color: theme.bg,
                display: "inline-block",
                transform: `scale(${interpolate(appear, [0, 1], [0.6, 1])})`,
                opacity: appear,
              }}
            >
              {w}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

/** Source figure / page screenshot, matted on the cream field with Ken Burns +
 * jump-cuts between stills. Falls back to a title card if no image was generated. */
export const FigureScene: React.FC<SceneProps> = ({ scene, theme }) => {
  const e = useEntrance();
  const images = sceneImages(scene);
  if (!images.length) return <SlideScene scene={scene} theme={theme} />;
  return (
    <AbsoluteFill
      style={{
        backgroundColor: theme.bg,
        justifyContent: "center",
        alignItems: "center",
        padding: 60,
      }}
    >
      <div
        style={{
          width: "100%",
          height: "100%",
          borderRadius: 18,
          overflow: "hidden",
          border: `10px solid ${theme.ink}`,
          transform: `scale(${interpolate(e, [0, 1], [0.94, 1])})`,
          opacity: e,
          backgroundColor: "#fff",
        }}
      >
        <ImageBeats images={images} theme={theme} />
      </div>
    </AbsoluteFill>
  );
};

/** User-supplied accent clip. Renders "via <source>" while it plays (fair-use §5). */
export const AccentClipScene: React.FC<SceneProps> = ({ scene, theme }) => {
  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      <CoverMedia scene={scene} kind="video" />
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

/** B-roll: real video if present, else Ken Burns over generated stills (the
 * cheap default — HANDOFF §11 keeps video spend down). Falls back to a slide. */
export const BrollScene: React.FC<SceneProps> = ({ scene, theme }) => {
  if (scene.videoUrl) {
    return (
      <AbsoluteFill style={{ backgroundColor: "#000" }}>
        <CoverMedia scene={scene} kind="video" />
      </AbsoluteFill>
    );
  }
  const images = sceneImages(scene);
  if (!images.length) return <SlideScene scene={scene} theme={theme} />;
  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      <ImageBeats images={images} theme={theme} />
    </AbsoluteFill>
  );
};

const REGISTRY: Record<string, React.FC<SceneProps>> = {
  slide: SlideScene,
  motion_text: MotionTextScene,
  figure: FigureScene,
  accent_clip: AccentClipScene,
  broll: BrollScene,
};

/** Dispatch a scene to its renderer; unknown types fall back to a slide. */
export const SceneRenderer: React.FC<SceneProps> = ({ scene, theme }) => {
  const Comp = REGISTRY[scene.type] ?? SlideScene;
  return <Comp scene={scene} theme={theme} />;
};
