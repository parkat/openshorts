import React from "react";
import {
  AbsoluteFill,
  Sequence,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { CaptionWord } from "../../lib/types";
import type { ExplainerTheme } from "../../lib/explainer-types";

/**
 * Retention-optimized captions (research-driven): tight word-by-word KARAOKE chunks,
 * big bold sans, the active word color-shifted to the brand accent + a glow (lit
 * slightly early), positioned in the CENTER band — out of the bottom ~25% platform
 * UI zone (like/share/handle/music). Strong outline for legibility over any footage.
 */
interface Props {
  captions: CaptionWord[];
  theme: ExplainerTheme;
}

const CHUNK = 3;       // words shown at once — mobile-readable karaoke
const LEAD_MS = 90;    // light the active word ~90ms before it's spoken

function chunkWords(words: CaptionWord[], size: number): CaptionWord[][] {
  const out: CaptionWord[][] = [];
  for (let i = 0; i < words.length; i += size) out.push(words.slice(i, i + size));
  return out;
}

export const ExplainerCaptions: React.FC<Props> = ({ captions, theme }) => {
  const { fps } = useVideoConfig();
  const words = captions.filter((w) => w.text && w.text.trim());
  const groups = chunkWords(words, CHUNK);

  return (
    <AbsoluteFill>
      {groups.map((g, i) => {
        const start = g[0].startMs;
        const end = g[g.length - 1].endMs;
        const from = Math.round((start / 1000) * fps);
        const dur = Math.max(1, Math.round(((end - start) / 1000) * fps));
        return (
          <Sequence key={i} from={from} durationInFrames={dur} layout="none">
            <ChunkView words={g} theme={theme} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};

const ChunkView: React.FC<{ words: CaptionWord[]; theme: ExplainerTheme }> = ({
  words,
  theme,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const nowMs = words[0].startMs + (frame / fps) * 1000 + LEAD_MS;
  let active = 0;
  for (let i = 0; i < words.length; i++) {
    if (nowMs >= words[i].startMs) active = i;
  }

  const stroke = [
    `5px 0 0 ${theme.ink}`,
    `-5px 0 0 ${theme.ink}`,
    `0 5px 0 ${theme.ink}`,
    `0 -5px 0 ${theme.ink}`,
    `4px 4px 0 ${theme.ink}`,
    `-4px 4px 0 ${theme.ink}`,
    `4px -4px 0 ${theme.ink}`,
    `-4px -4px 0 ${theme.ink}`,
    `0 6px 14px rgba(0,0,0,0.55)`,
  ].join(", ");

  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        top: "54%",
        transform: "translateY(-50%)",
        display: "flex",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          gap: "6px 18px",
          maxWidth: "84%",
        }}
      >
        {words.map((w, i) => {
          const on = i === active;
          return (
            <span
              key={i}
              style={{
                fontFamily: theme.captionFont,
                fontSize: 88,
                fontWeight: 900,
                textTransform: "uppercase",
                letterSpacing: "0.005em",
                lineHeight: 1.05,
                color: on ? theme.highlight : "#FFFFFF",
                textShadow: on
                  ? `${stroke}, 0 0 26px ${theme.highlight}, 0 0 44px ${theme.highlight}`
                  : stroke,
                display: "inline-block",
              }}
            >
              {w.text}
            </span>
          );
        })}
      </div>
    </div>
  );
};
