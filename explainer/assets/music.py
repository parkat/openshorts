"""Music stage: pick a CC0 bed and sidechain-duck it under the narration.

Music comes ONLY from the local CC0 library (Pixabay-License/FMA/Jamendo seed) —
never YouTube's Audio Library (not TikTok/Reels-safe) and never laundered from an
accent clip (§5). We duck the bed against the narration envelope with ffmpeg
`sidechaincompress` so the voice always sits on top, then hand the ducked WAV to
Remotion as the music layer.

Library dir: EXPLAINER_MUSIC_DIR (default assets/music/). Track pick is
deterministic per project (hash of the id) so re-renders are stable and A/B is
reproducible — no RNG.
"""
import os
import glob
import hashlib
import subprocess

MUSIC_DIR = os.environ.get("EXPLAINER_MUSIC_DIR", os.path.join("assets", "music"))
_EXTS = (".mp3", ".wav", ".m4a", ".ogg", ".flac")


def library(music_dir=None):
    """Sorted list of CC0 tracks in the library (stable order)."""
    d = music_dir or MUSIC_DIR
    files = []
    for ext in _EXTS:
        files.extend(glob.glob(os.path.join(d, f"*{ext}")))
    return sorted(files)


def pick_track(project_id, music_dir=None):
    """Deterministically choose a library track for a project (stable re-renders)."""
    tracks = library(music_dir)
    if not tracks:
        return None
    h = int(hashlib.sha256(str(project_id).encode()).hexdigest(), 16)
    return tracks[h % len(tracks)]


def duck(music_path, narration_path, out_path, music_gain_db=-9.0,
         threshold=0.03, ratio=8.0, attack=20.0, release=300.0):
    """Duck `music_path` under `narration_path` and write a narration-length WAV.

    Pre-attenuates the bed, then sidechain-compresses it by the narration so the
    music dips when the voice is present. Output is trimmed to the narration length
    (`-shortest`). Returns out_path."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    filt = (
        f"[0:a]volume={music_gain_db}dB[m];"
        f"[m][1:a]sidechaincompress="
        f"threshold={threshold}:ratio={ratio}:attack={attack}:release={release}[a]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", music_path,           # 0: music bed
        "-i", narration_path,       # 1: narration (sidechain key)
        "-filter_complex", filt,
        "-map", "[a]",
        "-ar", "24000", "-ac", "1",
        "-shortest",
        out_path,
    ]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if r.returncode != 0 or not os.path.isfile(out_path):
        raise RuntimeError(f"ffmpeg duck failed: {r.stderr.decode()[:300]}")
    return out_path


def build_bed(project_id, narration_path, out_path, music_dir=None):
    """Pick a CC0 track for the project and produce the ducked bed. Returns the
    out_path, or None if the library is empty (render just runs music-less)."""
    track = pick_track(project_id, music_dir)
    if not track:
        return None
    return duck(track, narration_path, out_path)
