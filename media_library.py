"""Server-side media library — ingest files that already live on the box.

A two-hour source is several GB, and no browser upload survives that: the dashboard
sits behind Cloudflare Access, and Cloudflare caps a single request body at 100MB
(free/Pro). So the file is copied to the box out-of-band (scp/SMB from the garage
PC) and the pipeline is pointed at it *by path* — nothing crosses the tunnel but
the path string.

Pasted paths are resolved against an allowlist of roots (`LOCAL_MEDIA_DIRS`), so a
path can't walk out of the media dirs into the rest of the filesystem.
"""

import os
import time

VIDEO_EXTS = {
    ".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi",
    ".ts", ".mts", ".m2ts", ".flv", ".wmv", ".mpg", ".mpeg",
}

# Walk depth under each root. Deep enough for "media/2026-09/raw/foo.mp4",
# shallow enough that a huge tree can't stall the listing endpoint.
MAX_DEPTH = 4
MAX_FILES = 500


def _default_roots():
    # `uploads` so browser-uploaded files stay addressable by the same picker;
    # `/app/media` is the bind mount added in docker-compose.yml for big sources.
    return [p for p in ("media", "/app/media", "uploads") if os.path.isdir(p)]


def media_roots():
    """Allowed roots, as absolute real paths. Non-existent entries are dropped."""
    raw = os.environ.get("LOCAL_MEDIA_DIRS", "")
    # os.pathsep is ':' in the Linux container, ';' on a Windows dev box. Accept ';'
    # on POSIX too so the same .env works either side — but never split on ':' under
    # Windows, where it lives inside every drive letter.
    normalized = raw.replace(";", os.pathsep) if os.pathsep != ";" else raw
    parts = [chunk.strip() for chunk in normalized.split(os.pathsep) if chunk.strip()]
    if not parts:
        parts = _default_roots()

    roots = []
    seen = set()
    for p in parts:
        try:
            real = os.path.realpath(os.path.abspath(p))
        except OSError:
            continue
        if os.path.isdir(real) and real not in seen:
            seen.add(real)
            roots.append(real)
    return roots


def resolve(path_str):
    """Validate a user-supplied path and return the real absolute path.

    Raises ValueError if it escapes every allowed root, doesn't exist, isn't a
    file, or isn't a video container we can feed to ffmpeg.
    """
    if not path_str or not str(path_str).strip():
        raise ValueError("No path given.")

    candidate = os.path.realpath(os.path.abspath(os.path.expanduser(str(path_str).strip())))
    roots = media_roots()
    if not roots:
        raise ValueError(
            "No media roots are configured on the server. Set LOCAL_MEDIA_DIRS "
            "in .env (or mount a directory at /app/media)."
        )

    inside = any(
        candidate == root or candidate.startswith(root + os.sep)
        for root in roots
    )
    if not inside:
        raise ValueError(
            f"Path is outside the allowed media directories ({', '.join(roots)})."
        )
    if not os.path.exists(candidate):
        raise ValueError(f"No such file on the server: {candidate}")
    if not os.path.isfile(candidate):
        raise ValueError(f"Not a file: {candidate}")
    if os.path.splitext(candidate)[1].lower() not in VIDEO_EXTS:
        raise ValueError(f"Not a recognized video file: {os.path.basename(candidate)}")
    return candidate


def _entry(root, full):
    try:
        st = os.stat(full)
    except OSError:
        return None
    return {
        "path": full,
        "rel_path": os.path.relpath(full, root).replace(os.sep, "/"),
        "name": os.path.basename(full),
        "root": root,
        "size_bytes": st.st_size,
        "size_mb": round(st.st_size / (1024 * 1024), 1),
        "modified": st.st_mtime,
    }


def list_files():
    """Every video file under every allowed root, newest first."""
    files = []
    for root in media_roots():
        root_depth = root.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root):
            if dirpath.rstrip(os.sep).count(os.sep) - root_depth >= MAX_DEPTH:
                dirnames[:] = []
            # Skip our own working dirs and dotfolders.
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("__pycache__",)]
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() not in VIDEO_EXTS:
                    continue
                entry = _entry(root, os.path.join(dirpath, fn))
                if entry:
                    files.append(entry)
                if len(files) >= MAX_FILES:
                    break
            if len(files) >= MAX_FILES:
                break
    files.sort(key=lambda f: f["modified"], reverse=True)
    return files


def library():
    """Payload for the dashboard's server-file picker."""
    return {
        "roots": media_roots(),
        "files": list_files(),
        "generated_at": time.time(),
    }
