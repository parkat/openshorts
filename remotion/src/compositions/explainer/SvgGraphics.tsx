import React from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { ExplainerScene, ExplainerTheme } from "../../lib/explainer-types";

/**
 * SVG graphics for text beats — an animated vector instead of a plain backdrop.
 * Two sources:
 *   - scene.svgUrl : a user-supplied SVG (assets/svg/) animated generically
 *     (spring-in + gentle float + reveal wipe) so ANY file looks intentional.
 *   - scene.svgKind: a built-in animated graphic (network | warning | bars) that
 *     we fully control (moving parts, draw-on).
 * Rendered centered on a subtle brand field; the captions stay the only text.
 */

interface Props {
  scene: ExplainerScene;
  theme: ExplainerTheme;
}

function useSpringIn(delay = 0): number {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({
    frame: frame - delay,
    fps,
    config: { mass: 0.6, stiffness: 130, damping: 15 },
  });
}

function accentOf(theme: ExplainerTheme, role?: string): string {
  const order = ["hook", "setup", "thing", "why", "button", "escalate"];
  const i = role ? order.indexOf(role) : -1;
  return theme.rainbow[(i >= 0 ? i : 0) % theme.rainbow.length] ?? theme.rainbow[0];
}

/** Subtle branded field behind the graphic (no text). */
const Field: React.FC<{ theme: ExplainerTheme; children: React.ReactNode }> = ({
  theme,
  children,
}) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill
      style={{
        backgroundColor: theme.bg,
        overflow: "hidden",
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: "-30%",
          background: `repeating-linear-gradient(120deg, ${theme.rainbow.join(", ")})`,
          opacity: 0.08,
          transform: `translateX(${((frame * 1.2) % 240) - 120}px) rotate(6deg)`,
        }}
      />
      {children}
    </AbsoluteFill>
  );
};

/** A user-supplied SVG file, animated generically. */
const LoadedSvg: React.FC<{ src: string }> = ({ src }) => {
  const e = useSpringIn();
  const frame = useCurrentFrame();
  const float = Math.sin(frame / 24) * 12;
  return (
    <div
      style={{
        width: "72%",
        height: "72%",
        transform: `translateY(${float}px) scale(${interpolate(e, [0, 1], [0.6, 1])})`,
        opacity: e,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      <Img src={src} style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }} />
    </div>
  );
};

// --- Built-in animated graphics ---

const NetworkGraphic: React.FC<Props> = ({ theme }) => {
  const frame = useCurrentFrame();
  const cols = [
    [0.25, 0.3, 0.55, 0.75],
    [0.2, 0.45, 0.7],
    [0.35, 0.6],
  ];
  const xs = [0.22, 0.5, 0.78];
  const nodes: { x: number; y: number; c: string }[] = [];
  cols.forEach((ys, ci) =>
    ys.forEach((y, ni) =>
      nodes.push({ x: xs[ci], y, c: theme.rainbow[(ci + ni) % theme.rainbow.length] })
    )
  );
  const W = 900;
  const H = 900;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="70%" height="70%">
      {cols.slice(0, -1).map((ys, ci) =>
        ys.flatMap((y1, i) =>
          cols[ci + 1].map((y2, j) => {
            const x1 = xs[ci] * W;
            const x2 = xs[ci + 1] * W;
            const yy1 = y1 * H;
            const yy2 = y2 * H;
            const dash = 40;
            const off = (frame * 4) % (dash * 2);
            return (
              <line
                key={`${ci}-${i}-${j}`}
                x1={x1}
                y1={yy1}
                x2={x2}
                y2={yy2}
                stroke={theme.ink}
                strokeOpacity={0.35}
                strokeWidth={3}
                strokeDasharray={`${dash} ${dash}`}
                strokeDashoffset={-off}
              />
            );
          })
        )
      )}
      {nodes.map((n, i) => {
        const pulse = 1 + 0.15 * Math.sin(frame / 12 + i);
        return (
          <circle
            key={i}
            cx={n.x * W}
            cy={n.y * H}
            r={26 * pulse}
            fill={n.c}
            stroke={theme.ink}
            strokeWidth={5}
          />
        );
      })}
    </svg>
  );
};

const WarningGraphic: React.FC<Props> = ({ theme, scene }) => {
  const frame = useCurrentFrame();
  const e = useSpringIn();
  const accent = accentOf(theme, scene.role);
  const glow = 0.5 + 0.5 * Math.sin(frame / 8);
  return (
    <svg viewBox="0 0 900 900" width="66%" height="66%" style={{ opacity: e }}>
      <polygon
        points="450,120 800,760 100,760"
        fill={accent}
        stroke={theme.ink}
        strokeWidth={26}
        strokeLinejoin="round"
        style={{ filter: `drop-shadow(0 0 ${18 * glow}px ${accent})` }}
      />
      <rect x="420" y="330" width="60" height="230" rx="26" fill={theme.bg} />
      <circle cx="450" cy="650" r="36" fill={theme.bg} />
    </svg>
  );
};

const BarsGraphic: React.FC<Props> = ({ theme }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const heights = [0.35, 0.55, 0.45, 0.8, 0.95];
  const W = 900;
  const H = 900;
  const base = 780;
  const bw = 120;
  const gap = 40;
  const startX = (W - (heights.length * bw + (heights.length - 1) * gap)) / 2;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="70%" height="70%">
      <line x1={80} y1={base} x2={W - 80} y2={base} stroke={theme.ink} strokeWidth={6} />
      {heights.map((h, i) => {
        const grow = spring({ frame: frame - i * 6, fps, config: { damping: 14 } });
        const hh = h * 560 * grow;
        return (
          <rect
            key={i}
            x={startX + i * (bw + gap)}
            y={base - hh}
            width={bw}
            height={hh}
            rx={12}
            fill={theme.rainbow[i % theme.rainbow.length]}
            stroke={theme.ink}
            strokeWidth={5}
          />
        );
      })}
    </svg>
  );
};

const ChipGraphic: React.FC<Props> = ({ theme, scene }) => {
  const frame = useCurrentFrame();
  const accent = accentOf(theme, scene.role);
  const glow = 0.4 + 0.6 * Math.abs(Math.sin(frame / 14));
  const pins = [0, 1, 2, 3, 4];
  return (
    <svg viewBox="0 0 900 900" width="62%" height="62%">
      {pins.map((i) => {
        const p = 250 + i * 90;
        return (
          <g key={i} fill={theme.ink}>
            <rect x={p} y={150} width={38} height={64} />
            <rect x={p} y={686} width={38} height={64} />
            <rect x={150} y={p} width={64} height={38} />
            <rect x={686} y={p} width={64} height={38} />
          </g>
        );
      })}
      <rect x={210} y={210} width={480} height={480} rx={28} fill={theme.bg} stroke={theme.ink} strokeWidth={16} />
      <rect
        x={330}
        y={330}
        width={240}
        height={240}
        rx={16}
        fill={accent}
        stroke={theme.ink}
        strokeWidth={12}
        style={{ filter: `drop-shadow(0 0 ${22 * glow}px ${accent})` }}
      />
      <text x={450} y={480} fill={theme.bg} fontSize={110} fontWeight={900} textAnchor="middle" fontFamily="Arial Black">AI</text>
    </svg>
  );
};

const RobotGraphic: React.FC<Props> = ({ theme, scene }) => {
  const frame = useCurrentFrame();
  const accent = accentOf(theme, scene.role);
  const blink = frame % 90 < 6 ? 0.08 : 1;
  return (
    <svg viewBox="0 0 900 900" width="58%" height="58%">
      <line x1={450} y1={190} x2={450} y2={120} stroke={theme.ink} strokeWidth={12} />
      <circle cx={450} cy={104} r={26} fill={accent} style={{ filter: `drop-shadow(0 0 ${10 + 6 * Math.sin(frame / 8)}px ${accent})` }} />
      <rect x={200} y={330} width={32} height={150} rx={12} fill={theme.ink} />
      <rect x={668} y={330} width={32} height={150} rx={12} fill={theme.ink} />
      <rect x={240} y={210} width={420} height={400} rx={54} fill={theme.bg} stroke={theme.ink} strokeWidth={18} />
      <ellipse cx={360} cy={370} rx={54} ry={54 * blink} fill={accent} stroke={theme.ink} strokeWidth={8} />
      <ellipse cx={540} cy={370} rx={54} ry={54 * blink} fill={accent} stroke={theme.ink} strokeWidth={8} />
      <rect x={340} y={490} width={220} height={38} rx={19} fill={theme.ink} />
    </svg>
  );
};

const GlobeGraphic: React.FC<Props> = ({ theme, scene }) => {
  const frame = useCurrentFrame();
  const accent = accentOf(theme, scene.role);
  return (
    <svg viewBox="0 0 900 900" width="64%" height="64%">
      <circle cx={450} cy={450} r={230} fill={accent} stroke={theme.ink} strokeWidth={16} />
      <ellipse cx={450} cy={450} rx={90} ry={230} fill="none" stroke={theme.bg} strokeWidth={6} opacity={0.75} />
      <ellipse cx={450} cy={450} rx={175} ry={230} fill="none" stroke={theme.bg} strokeWidth={6} opacity={0.6} />
      <ellipse cx={450} cy={450} rx={230} ry={80} fill="none" stroke={theme.bg} strokeWidth={6} opacity={0.75} />
      <line x1={220} y1={450} x2={680} y2={450} stroke={theme.bg} strokeWidth={6} opacity={0.6} />
      <g transform={`rotate(${frame * 1.6} 450 450)`}>
        <ellipse cx={450} cy={450} rx={320} ry={132} fill="none" stroke={theme.ink} strokeWidth={5} strokeDasharray="8 12" opacity={0.5} />
        <circle cx={770} cy={450} r={20} fill={theme.rainbow[3]} stroke={theme.ink} strokeWidth={6} />
      </g>
    </svg>
  );
};

const LockGraphic: React.FC<Props> = ({ theme, scene }) => {
  const frame = useCurrentFrame();
  const accent = accentOf(theme, scene.role);
  const e = useSpringIn();
  const glow = 0.4 + 0.4 * Math.sin(frame / 12);
  return (
    <svg viewBox="0 0 900 900" width="56%" height="56%" style={{ opacity: e }}>
      <path d="M330 410 v-70 a120 120 0 0 1 240 0 v70" fill="none" stroke={theme.ink} strokeWidth={40} strokeLinecap="round" />
      <rect
        x={270}
        y={405}
        width={360}
        height={320}
        rx={40}
        fill={accent}
        stroke={theme.ink}
        strokeWidth={18}
        style={{ filter: `drop-shadow(0 0 ${16 * glow}px ${accent})` }}
      />
      <circle cx={450} cy={520} r={44} fill={theme.ink} />
      <rect x={430} y={520} width={40} height={110} rx={16} fill={theme.ink} />
    </svg>
  );
};

const ClockGraphic: React.FC<Props> = ({ theme, scene }) => {
  const frame = useCurrentFrame();
  const accent = accentOf(theme, scene.role);
  const rad = (deg: number) => (deg * Math.PI) / 180;
  const hour = frame * 0.9;
  const sec = frame * 7;
  return (
    <svg viewBox="0 0 900 900" width="62%" height="62%">
      <circle cx={450} cy={450} r={258} fill={theme.bg} stroke={theme.ink} strokeWidth={20} />
      {Array.from({ length: 12 }).map((_, i) => {
        const a = rad(i * 30);
        return (
          <line
            key={i}
            x1={450 + 218 * Math.sin(a)}
            y1={450 - 218 * Math.cos(a)}
            x2={450 + 246 * Math.sin(a)}
            y2={450 - 246 * Math.cos(a)}
            stroke={theme.ink}
            strokeWidth={10}
          />
        );
      })}
      <line x1={450} y1={450} x2={450 + 120 * Math.sin(rad(hour))} y2={450 - 120 * Math.cos(rad(hour))} stroke={theme.ink} strokeWidth={20} strokeLinecap="round" />
      <line x1={450} y1={450} x2={450 + 200 * Math.sin(rad(sec))} y2={450 - 200 * Math.cos(rad(sec))} stroke={accent} strokeWidth={10} strokeLinecap="round" />
      <circle cx={450} cy={450} r={24} fill={accent} stroke={theme.ink} strokeWidth={8} />
    </svg>
  );
};

const BUILTINS: Record<string, React.FC<Props>> = {
  network: NetworkGraphic,
  warning: WarningGraphic,
  bars: BarsGraphic,
  chip: ChipGraphic,
  robot: RobotGraphic,
  globe: GlobeGraphic,
  lock: LockGraphic,
  clock: ClockGraphic,
};

export function hasSvg(scene: ExplainerScene): boolean {
  return !!scene.svgUrl || (!!scene.svgKind && scene.svgKind in BUILTINS);
}

export const SvgScene: React.FC<Props> = ({ scene, theme }) => {
  const Builtin = scene.svgKind ? BUILTINS[scene.svgKind] : undefined;
  return (
    <Field theme={theme}>
      {scene.svgUrl ? (
        <LoadedSvg src={scene.svgUrl} />
      ) : Builtin ? (
        <Builtin scene={scene} theme={theme} />
      ) : null}
    </Field>
  );
};
