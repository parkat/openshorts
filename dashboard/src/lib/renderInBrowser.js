import { getApiUrl } from '../config';

/**
 * Renders the ShortVideo composition on the server-side render-service
 * (Remotion + ffmpeg via OffthreadVideo) and returns a URL to the rendered MP4.
 *
 * NOTE: This previously rendered in-browser via @remotion/web-renderer
 * (renderMediaOnWeb / WebCodecs). That fails on browsers that lack H.264
 * WebCodecs decode support with "The video could not be decoded by the browser".
 * Rendering on the GPU host is browser-independent and reliable. The function
 * name is kept for compatibility with existing call sites.
 *
 * @param {object} params
 * @param {string} params.videoUrl - Source video URL (absolute or /videos/<jobId>/<file>)
 * @param {number} params.durationInSeconds - Clip duration (used to size the render)
 * @param {object|null} params.subtitles - SubtitleConfig
 * @param {object|null} params.hook - HookConfig
 * @param {object|null} params.effects - EffectsConfig
 * @param {string} params.jobId - Job id (required by the render-service)
 * @param {number} params.clipIndex - Clip index (required by the render-service)
 * @param {function} [params.onProgress] - Progress callback (0-1)
 * @param {AbortSignal} [params.signal] - Abort signal for cancellation
 * @returns {Promise<string>} URL of the rendered MP4 (served by the backend)
 */
export async function renderInBrowser({
    videoUrl,
    durationInSeconds = 30,
    subtitles = null,
    hook = null,
    effects = null,
    jobId,
    clipIndex,
    onProgress,
    signal,
}) {
    if (!jobId || clipIndex === undefined || clipIndex === null) {
        throw new Error('renderInBrowser requires jobId and clipIndex for server-side rendering');
    }

    const fps = 30;
    const durationInFrames = Math.max(1, Math.round((durationInSeconds || 30) * fps));

    // The render-service resolves a "/videos/<jobId>/<file>" path to its own static
    // server. Reduce the source URL to that path (strip origin / query).
    let videoPath = videoUrl;
    const m = typeof videoUrl === 'string' && videoUrl.match(/\/videos\/[^?#]+/);
    if (m) videoPath = m[0];

    // 1) Submit the render job
    const submitRes = await fetch(getApiUrl('/render'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            jobId,
            clipIndex,
            props: {
                videoUrl: videoPath,
                durationInFrames,
                fps,
                width: 1080,
                height: 1920,
                subtitles,
                hook,
                effects,
            },
        }),
        signal,
    });
    if (!submitRes.ok) {
        throw new Error(`Render request failed: ${await submitRes.text()}`);
    }
    const submit = await submitRes.json();
    const renderId = submit.renderId;
    if (!renderId) throw new Error('Render service did not return a renderId');

    // 2) Poll until the render finishes (or errors)
    // eslint-disable-next-line no-constant-condition
    while (true) {
        if (signal?.aborted) throw new DOMException('Render aborted', 'AbortError');
        await new Promise((r) => setTimeout(r, 1500));

        let status;
        try {
            const statusRes = await fetch(getApiUrl(`/render/${renderId}`), { signal });
            if (!statusRes.ok) continue; // transient; keep polling
            status = await statusRes.json();
        } catch (e) {
            if (signal?.aborted) throw e;
            continue; // transient network error; keep polling
        }

        if (typeof status.progress === 'number' && onProgress) {
            onProgress(Math.min(1, status.progress / 100));
        }

        if (status.status === 'done') {
            // outputUrl is a filesystem path like "/output/<jobId>/<file>.mp4".
            // The backend serves the same file at "/videos/<jobId>/<file>".
            const out = status.outputUrl || '';
            const om = out.match(/\/output\/([^/]+)\/(.+)$/);
            if (om) return getApiUrl(`/videos/${om[1]}/${om[2]}`);
            throw new Error(`Render finished but returned an unexpected output path: ${out}`);
        }
        if (status.status === 'error') {
            throw new Error(status.error || 'Server render failed');
        }
    }
}

/**
 * Triggers a download of a URL as an MP4 file.
 */
export function downloadBlobUrl(blobUrl, filename = 'output.mp4') {
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}
