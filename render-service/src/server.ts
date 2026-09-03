import express from "express";
import { v4 as uuidv4 } from "uuid";
import { z } from "zod";
import { initBundle } from "./bundle.js";
import { executeRender } from "./render-worker.js";
import { aidRouter } from "./aid.js";

// --- Render status types ---

export type RenderStatus = "queued" | "rendering" | "done" | "error";

export interface RenderJob {
  renderId: string;
  jobId: string;
  clipIndex: number;
  status: RenderStatus;
  progress: number;
  outputUrl?: string;
  error?: string;
}

// In-memory render job map
export const renderJobs = new Map<string, RenderJob>();

// --- Request validation schema ---

// Props are validated per-composition by Remotion's own zod schema at
// selectComposition time, so accept any object here and only require the common
// render dimensions. `composition` selects the Root composition (default
// "ShortVideo"; "ExplainerShort" for the explainer lane).
const renderRequestSchema = z.object({
  jobId: z.string().min(1),
  clipIndex: z.number().int().min(0),
  composition: z.string().min(1).optional(),
  props: z
    .object({
      durationInFrames: z.number().int().positive(),
      fps: z.number().positive(),
      width: z.number().int().positive(),
      height: z.number().int().positive(),
    })
    .passthrough(),
});

// --- Express app ---

const app = express();
app.use(express.json({ limit: "10mb" }));

const PORT = parseInt(process.env.PORT || "3100", 10);
const OUTPUT_DIR = process.env.OUTPUT_DIR || "/output";

// Serve video files from the shared output volume so Remotion can access them via HTTP
app.use("/output", express.static(OUTPUT_DIR));

/**
 * Rewrite backend-relative asset URLs to the renderer's own static server so
 * Remotion (running here) can fetch them. Handles two forms anywhere in the
 * props tree:
 *   - "/videos/<job>/<file>"  (backend clip route)  -> /output/<job>/<file>
 *   - "/output/<...>"         (shared volume path)  -> served as-is
 * Absolute http(s) URLs and everything else pass through untouched.
 */
function resolveAssetUrls(value: unknown): unknown {
  if (typeof value === "string") {
    const m = value.match(/^\/videos\/([^/]+)\/(.+)$/);
    if (m) return `http://localhost:${PORT}/output/${m[1]}/${m[2]}`;
    if (value.startsWith("/output/"))
      return `http://localhost:${PORT}${value}`;
    return value;
  }
  if (Array.isArray(value)) return value.map(resolveAssetUrls);
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) out[k] = resolveAssetUrls(v);
    return out;
  }
  return value;
}

// Health check
app.get("/health", (_req, res) => {
  res.json({ ok: true });
});

// Compile + validate generated motion-graphic aids (POST /aid/compile, /aid/probe).
app.use(aidRouter);

// Submit a render job
app.post("/render", (req, res) => {
  const parsed = renderRequestSchema.safeParse(req.body);

  if (!parsed.success) {
    res.status(400).json({
      error: "Invalid request body",
      details: parsed.error.issues,
    });
    return;
  }

  const { jobId, clipIndex, props } = parsed.data;
  const composition = parsed.data.composition || "ShortVideo";
  const renderId = uuidv4();

  const job: RenderJob = {
    renderId,
    jobId,
    clipIndex,
    status: "queued",
    progress: 0,
  };

  renderJobs.set(renderId, job);

  console.log(
    `[render] Queued render ${renderId} for job=${jobId} clip=${clipIndex} comp=${composition}`
  );

  // Resolve any asset URL anywhere in the props (ShortVideo's videoUrl, and the
  // explainer scene list's narration/music/image/video refs) to the renderer's
  // own static server, which serves /output/* from the shared Docker volume.
  const resolvedProps = resolveAssetUrls(props) as Record<string, unknown>;

  // Fire and forget - render runs in background
  executeRender({
    renderId,
    jobId,
    clipIndex,
    composition,
    props: resolvedProps,
  }).catch((err) => {
    console.error(`[render] Unhandled error for ${renderId}:`, err);
    const existingJob = renderJobs.get(renderId);
    if (existingJob) {
      existingJob.status = "error";
      existingJob.error =
        err instanceof Error ? err.message : "Unknown error";
    }
  });

  res.status(202).json({ renderId, status: "queued" });
});

// Get render status
app.get("/render/:renderId", (req, res) => {
  const { renderId } = req.params;
  const job = renderJobs.get(renderId);

  if (!job) {
    res.status(404).json({ error: "Render not found" });
    return;
  }

  const response: Record<string, unknown> = {
    renderId: job.renderId,
    status: job.status,
  };

  if (job.progress !== undefined) {
    response.progress = job.progress;
  }
  if (job.outputUrl) {
    response.outputUrl = job.outputUrl;
  }
  if (job.error) {
    response.error = job.error;
  }

  res.json(response);
});

// --- Start server ---

async function main() {
  console.log("[render-service] Initializing Remotion bundle...");
  await initBundle();
  console.log("[render-service] Bundle ready.");

  app.listen(PORT, () => {
    console.log(`[render-service] Listening on port ${PORT}`);
  });
}

main().catch((err) => {
  console.error("[render-service] Fatal error during startup:", err);
  process.exit(1);
});
