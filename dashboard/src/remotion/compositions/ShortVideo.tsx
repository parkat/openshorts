import React from "react";
import { AbsoluteFill, Video } from "remotion";
import type { ShortVideoProps } from "../lib/types";
import { Subtitles } from "./Subtitles";
import { HookOverlay } from "./HookOverlay";
import { VideoEffects } from "./VideoEffects";

/**
 * Main composition that layers all post-processing on top of the base video.
 * Uses the classic remotion <Video> (HTML5 <video> element) so the in-modal
 * Player preview decodes H.264 natively in the browser. Actual exports are
 * rendered server-side by the render-service (which uses OffthreadVideo/ffmpeg),
 * so this composition is only used for live preview here.
 */
export const ShortVideo: React.FC<Record<string, unknown>> = (rawProps) => {
  const { videoUrl, subtitles, hook, effects } =
    rawProps as unknown as ShortVideoProps;
  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {/* Layer 1: Base video with optional zoom/color effects */}
      <VideoEffects config={effects}>
        <Video
          src={videoUrl}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />
      </VideoEffects>

      {/* Layer 2: Animated subtitles */}
      {subtitles && <Subtitles config={subtitles} />}

      {/* Layer 3: Hook text overlay */}
      {hook && <HookOverlay config={hook} />}
    </AbsoluteFill>
  );
};
