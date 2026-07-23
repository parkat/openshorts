"""Accent-clip stage: fetch parkat's pasted YouTube URLs, trim to the in/out
window, enforce the fair-use guardrails (HANDOFF §5), and log provenance.

Guardrails are engineering guardrails (defensible-by-construction, reach-first),
surfaced as fixable flags — never a silent drop. `block`-level flags must be
resolved or explicitly overridden in review gate 1 before render; `warn`-level
flags are advisory. Every fetched clip is recorded in the `clips` table
(url/channel/timestamps/fetch date) so a dispute is answerable.
"""
import os
import subprocess

import store
from explainer import transcript as tr

# Fair-use thresholds (§5). Overridable in gate 1.
SOFT_CLIP_S = 15.0      # warn beyond this per clip
HARD_CLIP_S = 30.0      # block: no >30s uninterrupted excerpt
NARRATION_DOMINANT = 0.60   # ≥60% of runtime must be original narration/visuals


def check_guardrails(clips, narration_seconds):
    """Evaluate the fair-use guardrails over the accent clips.

    `clips`: [{index, start_s, end_s, ...}]. `narration_seconds`: the short's
    runtime (≈ narration length). Returns [{level, code, clip_index, message}],
    worst (block) first. Empty list == clean.
    """
    flags = []
    total_clip = 0.0
    for c in clips:
        idx = c.get("index")
        dur = max(0.0, float(c.get("end_s", 0)) - float(c.get("start_s", 0)))
        total_clip += dur
        if dur > HARD_CLIP_S:
            flags.append({"level": "block", "code": "clip_too_long", "clip_index": idx,
                          "message": f"clip {idx} is {dur:.0f}s — exceeds the {HARD_CLIP_S:.0f}s hard cap; trim it."})
        elif dur > SOFT_CLIP_S:
            flags.append({"level": "warn", "code": "clip_long", "clip_index": idx,
                          "message": f"clip {idx} is {dur:.0f}s — over the {SOFT_CLIP_S:.0f}s soft cap; consider trimming."})
        if narration_seconds and dur > narration_seconds:
            flags.append({"level": "block", "code": "clip_exceeds_narration", "clip_index": idx,
                          "message": f"clip {idx} ({dur:.0f}s) is longer than the narration ({narration_seconds:.0f}s)."})

    # Narration-dominance (§5) is judged at render from DISPLAYED durations
    # (render.accent_display_fraction), not fetched window length — a fetched 14s
    # clip that only fills a 4s slot shouldn't trip the dominance warn here.
    order = {"block": 0, "warn": 1}
    return sorted(flags, key=lambda f: order.get(f["level"], 9))


def has_blocks(flags):
    return any(f["level"] == "block" for f in flags)


def fetch_clip(url, start_s, end_s, out_path):
    """Download just the [start_s, end_s] window of a YouTube URL via yt-dlp
    (section download so we don't pull the whole video), re-encoded to a clean
    9:16-friendly H.264/AAC clip. Returns out_path."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    section = f"*{float(start_s):.2f}-{float(end_s):.2f}"
    cmd = [
        "yt-dlp", "--no-playlist",
        "--force-overwrites",          # re-fetch cleanly if the window changed (don't keep a stale clip)
        "--download-sections", section,
        "--force-keyframes-at-cuts",
        "-f", "bv*[height<=1920]+ba/b",
        "--recode-video", "mp4",
        "-o", out_path,
        url,
    ]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0 or not os.path.isfile(out_path):
        raise RuntimeError(f"yt-dlp failed for {url}: {r.stderr.decode()[:300]}")
    return out_path


def log_provenance(session, project_id, url, start_s, end_s, local_path, channel=""):
    """Record one accent clip in the `clips` table (dispute-ready)."""
    row = store.Clip(project_id=project_id, url=url, channel=channel,
                     start_s=float(start_s), end_s=float(end_s), local_path=local_path)
    session.add(row)
    return row


def gather_from_plan(session, project_id, selections, out_dir, narration_seconds=None):
    """Fetch the clip-finder's selected windows (each already tied to a shot_index),
    guardrail-check, and log provenance. `selections`: [{shot_index, url, in, out,
    channel, ...}] from `clipfinder.plan`.

    Returns {"shot_assets": {shot_index: {videoUrl[, attribution]}}, "flags": [...]}
    — shot_assets keyed by the exact shot the window was chosen for (no order guess)."""
    from explainer.render import job_id_for
    job_id = job_id_for(project_id)
    records, prefetch_flags, shot_assets = [], [], {}
    for k, sel in enumerate(selections or []):
        start_s, end_s = float(sel.get("in", 0)), float(sel.get("out", 0))
        out_path = os.path.join(out_dir, f"clip{k}.mp4")
        rec = {"index": sel.get("shot_index"), "start_s": start_s, "end_s": end_s}
        records.append(rec)
        try:
            fetch_clip(sel.get("url", ""), start_s, end_s, out_path)
            log_provenance(session, project_id, sel.get("url", ""), start_s, end_s,
                           out_path, sel.get("channel") or "")
            rel = f"/output/{job_id}/{os.path.basename(out_path)}"
            # speechUrl = the audio source (baked into the master if this shot speaks);
            # videoUrl = the default visual (his face). An aid shot overrides the visual
            # with its generated aid clips but still uses speechUrl for the voice.
            entry = {"videoUrl": rel, "speechUrl": rel}
            if sel.get("channel"):
                entry["attribution"] = f"via {sel['channel']}"
            # Pull the video's OWN captions for this window (no ASR) — align uses these
            # for the soundbite's words and only falls back to whisper if they're
            # missing/malformed.
            try:
                vtt = tr.ensure_vtt(sel.get("url", ""), out_dir)
                wjson = os.path.join(out_dir, f"clip{k}.words.json")
                if vtt and tr.save_window(vtt, start_s, end_s, wjson):
                    entry["wordsUrl"] = f"/output/{job_id}/{os.path.basename(wjson)}"
            except Exception:  # noqa: BLE001 — captions are best-effort; ASR covers it
                pass
            shot_assets[int(sel["shot_index"])] = entry
        except Exception as e:  # noqa: BLE001 — surface as a fixable flag, don't abort
            prefetch_flags.append({"level": "block", "code": "fetch_failed",
                                   "clip_index": sel.get("shot_index"),
                                   "message": f"could not fetch clip for shot {sel.get('shot_index')} ({sel.get('url')}): {e}"})

    flags = check_guardrails(records, narration_seconds) + prefetch_flags
    order = {"block": 0, "warn": 1}
    return {"shot_assets": shot_assets,
            "flags": sorted(flags, key=lambda f: order.get(f["level"], 9))}


def gather_accent_clips(session, project_id, sources, out_dir, narration_seconds=None):
    """Fetch every YouTube accent source for a project, trim, guardrail-check, and
    log provenance. `sources`: the topic's source list [{type, url, in, out, ...}].

    Returns {"clips": [{index, url, start_s, end_s, local_path, channel}],
             "flags": [...guardrail flags...]}. Fetch failures become a block flag
    rather than aborting the batch."""
    accent = [s for s in (sources or []) if s.get("type") == "youtube"]
    clips, prefetch_flags = [], []
    for i, s in enumerate(accent):
        start_s = float(s.get("in") or 0)
        end_s = float(s.get("out") or 0)
        out_path = os.path.join(out_dir, f"clip{i}.mp4")
        rec = {"index": i, "url": s.get("url", ""), "start_s": start_s,
               "end_s": end_s, "channel": s.get("channel") or s.get("label") or ""}
        try:
            fetch_clip(rec["url"], start_s, end_s, out_path)
            rec["local_path"] = out_path
            log_provenance(session, project_id, rec["url"], start_s, end_s, out_path, rec["channel"])
        except Exception as e:  # noqa: BLE001 — surface as a fixable flag, don't abort
            rec["local_path"] = ""
            prefetch_flags.append({"level": "block", "code": "fetch_failed", "clip_index": i,
                                   "message": f"could not fetch clip {i} ({rec['url']}): {e}"})
        clips.append(rec)

    flags = check_guardrails(clips, narration_seconds) + prefetch_flags
    order = {"block": 0, "warn": 1}
    return {"clips": clips, "flags": sorted(flags, key=lambda f: order.get(f["level"], 9))}
