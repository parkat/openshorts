import React from "react";
import { z } from "zod";
import { AbsoluteFill } from "remotion";
import { DynamicAid } from "./DynamicAid";
import {
  DEFAULT_THEME,
  explainerThemeSchema,
  type ExplainerTheme,
} from "../../lib/explainer-types";

/**
 * A bare harness around one generated aid, used by `POST /aid/probe` in the
 * render-service to validate LLM-authored code before it ever reaches a real
 * project.
 *
 * The point of probing through a REAL composition (rather than eval-ing the code
 * in Node) is that it exercises the exact runtime path a render uses — same
 * evaluator, same hook wiring, same Chromium. A component that type-checks but
 * paints nothing only reveals itself here.
 *
 * The fallback is deliberately a flat, uniform field: the probe rejects blank
 * frames, so if the code fails the harness renders something the blankness check
 * catches, rather than a busy backdrop that would mask the failure.
 */

export interface AidProbeProps {
  aidCode: string;
  aidProps: Record<string, unknown>;
  theme: ExplainerTheme;
  durationInFrames: number;
  fps: number;
  width: number;
  height: number;
}

export const aidProbePropsSchema = z.object({
  aidCode: z.string(),
  aidProps: z.record(z.string(), z.unknown()),
  theme: explainerThemeSchema,
  durationInFrames: z.number().int().positive(),
  fps: z.number().positive(),
  width: z.number().int().positive(),
  height: z.number().int().positive(),
});

export const DEFAULT_AID_PROBE_PROPS: AidProbeProps = {
  aidCode: "",
  aidProps: {},
  theme: DEFAULT_THEME,
  durationInFrames: 120,
  fps: 30,
  width: 1080,
  height: 1920,
};

export const AidProbe: React.FC<Record<string, unknown>> = (rawProps) => {
  const props = rawProps as unknown as AidProbeProps;
  const theme = props.theme ?? DEFAULT_THEME;

  return (
    <DynamicAid
      code={props.aidCode}
      aidProps={props.aidProps}
      theme={theme}
      fallback={<AbsoluteFill style={{ backgroundColor: theme.bg }} />}
    />
  );
};
