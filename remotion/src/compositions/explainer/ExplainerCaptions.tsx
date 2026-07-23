import React from "react";
import {
  AbsoluteFill,
  Sequence,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { CaptionWord } from "../../lib/types";
import type { ExplainerTheme } from "../../lib/explainer-types";
import { groupCaptionsIntoBlocks, getActiveWordIndex } from "../../lib/captions";

/**
 * Brand-styled word-level captions for the explainer lane. Reuses the shared
 * block-grouping (matches generate_srt) and highlights the active word in the
 * brand accent, so captions ride the real narration timing from align.py.
 */
interface Props {
  captions: CaptionWord[];
  theme: ExplainerTheme;
}

export const ExplainerCaptions: React.FC<Props> = ({ captions, theme }) => {
  const { fps } = useVideoConfig();
  const blocks = groupCaptionsIntoBlocks(captions);

  return (
    <AbsoluteFill>
      {blocks.map((block, i) => {
        const from = Math.round((block.startMs / 1000) * fps);
        const dur = Math.max(
          1,
          Math.round(((block.endMs - block.startMs) / 1000) * fps)
        );
        return (
          <Sequence key={i} from={from} durationInFrames={dur} layout="none">
            <CaptionBlock block={block} theme={theme} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};

const CaptionBlock: React.FC<{
  block: ReturnType<typeof groupCaptionsIntoBlocks>[number];
  theme: ExplainerTheme;
}> = ({ block, theme }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const nowMs = block.startMs + (frame / fps) * 1000;
  const active = getActiveWordIndex(block.words, nowMs);

  const stroke = [
    `4px 0 0 ${theme.ink}`,
    `-4px 0 0 ${theme.ink}`,
    `0 4px 0 ${theme.ink}`,
    `0 -4px 0 ${theme.ink}`,
  ].join(", ");

  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: "11%",
        display: "flex",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          gap: "6px 12px",
          maxWidth: "84%",
        }}
      >
        {block.words.map((w, i) => (
          <span
            key={i}
            style={{
              fontFamily: theme.captionFont,
              fontSize: 68,
              fontWeight: 900,
              textTransform: "uppercase",
              letterSpacing: "0.01em",
              color: i === active ? theme.highlight : "#FFFFFF",
              textShadow: stroke,
              display: "inline-block",
            }}
          >
            {w.text}
          </span>
        ))}
      </div>
    </div>
  );
};
