"""Ingest stage: one long-form URL -> one local download + one timed transcript.

Everything downstream cuts from the local file, so this is the ONLY network fetch
in the lane. That is deliberate: yt-dlp section-fetches get the box's IP
rate-limited after roughly 5-8 requests, which is fewer than a single batch of
candidates. One full download side-steps it entirely.

The file lands at `cache/youtube/<video_id>.mp4` — the exact path
`explainer.assets.clips._cached_full` probes — so `fetch_clip` picks it up with no
further wiring. It is deliberately NOT run through `explainer.cache.put`: that
copies bytes into a content-addressed name, which would double a multi-GB download
and hide it from `_cached_full`.
"""
import os
import glob
import subprocess

from explainer import clipfinder as cf
from explainer import transcript as tr

CACHE_DIR = os.environ.get("EXPLAINER_CACHE", "cache")

# Prefer H.264: "best by height" routinely picks AV1/VP9 streams whose CDN URLs
# 403 on the ranged requests every later stage makes, and H.264 is what ffmpeg
# wants anyway. 1080p is ample — the render fits the clip to a 1080px width.
FORMAT = ("bv*[height<=1080][vcodec^=avc1]+ba[acodec^=mp4a]/"
          "bv*[height<=1080][vcodec^=avc1]+ba/"
          "b[ext=mp4]/bv*[height<=1080]+ba/b")

# YouTube player clients to try, in order. Which ones work changes without
# warning: on 2026-08-22 the default and `tv` clients returned 403 / "the page
# needs to be reloaded" for a video whose metadata read fine, while `android`
# downloaded it — and yt-dlp could not fall back to impersonation because
# curl_cffi is not installed in the image. Trying a list beats pinning one.
CLIENTS = [c.strip() for c in
           os.environ.get("CLIPS_YT_CLIENTS", "android,default,tv,web_safari").split(",")
           if c.strip()]


def youtube_dir():
    d = os.path.join(CACHE_DIR, "youtube")
    os.makedirs(d, exist_ok=True)
    return d


def cached_path(video_id):
    return os.path.join(youtube_dir(), f"{video_id}.mp4")


def cached_vtt(video_id):
    """The auto-caption track next to the cached download, if yt-dlp wrote one."""
    hits = sorted(glob.glob(os.path.join(youtube_dir(), f"{video_id}*.vtt")))
    plain = [h for h in hits if h.endswith(".en.vtt")]
    return (plain or hits or [None])[0]


def download(url, video_id, log=print):
    """Fetch the full video + its English auto-captions in ONE yt-dlp call.

    Idempotent: an existing download is reused untouched. Returns its path.
    """
    out = cached_path(video_id)
    if os.path.isfile(out) and os.path.getsize(out) > 0:
        log(f"  cached download: {out} ({os.path.getsize(out) / 1e6:.0f} MB)")
        return out
    log(f"  downloading {url} -> {out}")
    last = ""
    for client in CLIENTS:
        cmd = [
            "yt-dlp", "--no-playlist", "-f", FORMAT, "--merge-output-format", "mp4",
            # Captions in the same pass — `transcript.ensure_vtt` already knows to
            # look for them here, so the moments stage costs no extra fetch.
            "--write-auto-subs", "--sub-langs", "en.*", "--convert-subs", "vtt",
            "-o", os.path.join(youtube_dir(), f"{video_id}.%(ext)s"),
        ]
        if client != "default":
            cmd += ["--extractor-args", f"youtube:player_client={client}"]
        cmd.append(url)
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if os.path.isfile(out) and os.path.getsize(out) > 0:
            log(f"  downloaded {os.path.getsize(out) / 1e6:.0f} MB (client={client})")
            return out
        last = r.stderr.decode(errors="replace").strip().splitlines()[-1:] or [""]
        log(f"  client={client} failed: {last[0][:120]}")
    raise RuntimeError(f"yt-dlp failed for {url} on every client "
                       f"({', '.join(CLIENTS)}): {last[0] if last else ''}")


def transcript_segments(url, video_id, video_path, log=print):
    """Timed transcript for the whole video as [{start,end,text}], plus its source.

    Auto-captions first (free, already on disk). Whisper is the fallback for a video
    with no caption track — accurate but it re-listens to the entire runtime, so it
    is a fallback, never the default.
    """
    vtt = cached_vtt(video_id) or tr.ensure_vtt(url, youtube_dir(), video_id)
    if vtt and os.path.isfile(vtt):
        segs = cf.parse_vtt(vtt)
        if segs:
            log(f"  transcript: {len(segs)} segments from auto-captions")
            return segs, "vtt", vtt
        log("  auto-caption track parsed empty — falling back to whisper")
    else:
        log("  no auto-captions for this video — falling back to whisper")

    import subtitles
    result = subtitles.transcribe_audio(video_path)
    segs = [{"start": round(s["start"], 1), "end": round(s["end"], 1),
             "text": (s.get("text") or "").strip()}
            for s in result.get("segments", []) if (s.get("text") or "").strip()]
    log(f"  transcript: {len(segs)} segments from whisper")
    return segs, "asr", ""
