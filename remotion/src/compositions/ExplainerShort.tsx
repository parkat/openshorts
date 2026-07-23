import React from "react";
import { AbsoluteFill, Audio, Sequence, useVideoConfig } from "remotion";
import type { ExplainerShortProps } from "../lib/explainer-types";
import { SceneRenderer } from "./explainer/Scenes";
import { VhsOverlay } from "./explainer/VhsOverlay";
import { ExplainerCaptions } from "./explainer/ExplainerCaptions";

/**
 * "Scientific Awareness" explainer composition — a data-driven 9:16 short.
 *
 * Layers (bottom -> top):
 *   1. per-shot scenes (slide / motion_text / figure / accent_clip / broll),
 *      sequenced by the ms boundaries align.py computed;
 *   2. narration audio over the whole short + optional ducked music bed;
 *   3. word-level captions riding the narration;
 *   4. the VHS texture pass.
 *
 * Duration/fps/dimensions come from calculateMetadata in Root, derived from the
 * narration length — so the video is exactly as long as the audio.
 */
export const ExplainerShort: React.FC<Record<string, unknown>> = (rawProps) => {
  const props = rawProps as unknown as ExplainerShortProps;
  const { fps } = useVideoConfig();
  const { scenes, theme, captions, narrationUrl, musicUrl } = props;

  const toFrame = (ms: number) => Math.round((ms / 1000) * fps);

  return (
    <AbsoluteFill style={{ backgroundColor: theme.bg }}>
      {/* Layer 1: scenes */}
      {scenes.map((scene, i) => {
        const from = toFrame(scene.startMs);
        const dur = Math.max(1, toFrame(scene.endMs) - from);
        return (
          <Sequence key={i} from={from} durationInFrames={dur}>
            <SceneRenderer scene={scene} theme={theme} />
          </Sequence>
        );
      })}

      {/* Layer 2: audio */}
      {narrationUrl && <Audio src={narrationUrl} />}
      {musicUrl && <Audio src={musicUrl} volume={0.18} />}

      {/* Layer 3: captions */}
      {captions.length > 0 && (
        <ExplainerCaptions captions={captions} theme={theme} />
      )}

      {/* Layer 4: VHS texture */}
      {theme.vhs && <VhsOverlay />}
    </AbsoluteFill>
  );
};
