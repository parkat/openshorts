# OPERATING.md — driving the deployment

How to reach and operate the GPU box from any machine (desktop, laptop, a fresh
Claude Code session). Written 2026-07-24.

---

## 1. Reaching the box

The GPU box is **`192.168.68.72`** (`i9-32g-p100-2070`), user **`pt`**. It runs the
whole stack in Docker. **It gets wiped periodically — treat it as disposable.**
Nothing durable should live outside `./output`, `./archive` and Docker.

Access is over **Tailscale**, via a subnet router on persistent Proxmox
infrastructure (so the box itself needs nothing installed):

```
laptop ─tailscale─→ CT100 "pve-home-agent" (100.108.154.84, advertises 192.168.68.0/22)
                          └─→ GPU box 192.168.68.72
```

Suggested `~/.ssh/config` (key name will vary per machine):

```
Host p100-guardian          # PRIMARY — direct, via the subnet route
    HostName 192.168.68.72
    User pt
    IdentityFile ~/.ssh/openshorts_box

Host pve-hub                # the Proxmox subnet router
    HostName 100.108.154.84
    User root
    IdentityFile ~/.ssh/openshorts_box

Host box-via-hub            # FALLBACK — survives a box wipe (see below)
    HostName 192.168.68.72
    User pt
    ProxyJump pve-hub
    IdentityFile ~/.ssh/openshorts_box
```

**After a box wipe** `~/.ssh/authorized_keys` on the box is gone with it. CT100
holds its own credential (`/etc/hub/ssh/id_ed25519`, trusted as `hub-agent@home`)
that the box's provisioning restores, so `box-via-hub` is the recovery path. Any
new personal key must be added to the box's provisioning or it only survives until
the next wipe.

Proxmox host itself: `root@192.168.68.59` (`R340-vm`, PVE 9). Containers:
100 `home-agent` (cloudflared + tailscale), 104 `nvr` (holds `/etc/nvr-creds/gpu-box.key`).

## 2. Deploying changes

The repo lives at `/home/pt/openshorts` on the box. Ship by checking files out of
origin — **do not edit on the box**.

```bash
ssh p100-guardian 'cd ~/openshorts && git fetch -q origin \
  && sudo chown -R pt:pt explainer \
  && git checkout origin/<branch> -- <paths...> \
  && git reset -q \
  && sudo chown -R 999:999 explainer'
```

- **The chown dance is required.** The container runs as uid 999; `git checkout`
  writes as `pt` and the backend then can't read `explainer/`. Chown to `pt` first,
  check out, chown back to 999.
- **Always `git fetch` first** — a stale `origin` ref silently ships the previous
  commit and you debug a fix that was never deployed.

Then restart what you touched:

| Changed | Command |
|---|---|
| `app.py`, `explainer/**`, `*.py` | `sudo docker restart openshorts-backend` |
| `dashboard/src/**` | `sudo docker restart openshorts-frontend` (runs `vite build && preview`) |
| `remotion/src/**` | `sudo docker compose -f docker-compose.yml -f docker-compose.gpu.yml build renderer && ... up -d renderer` |

Renderer rebuilds take several minutes — run them in the background and wait on the
container being recreated, not on the command returning.

## 3. Driving the pipeline

Two equivalent drivers over the same SQLite state (`archive/openshorts.db`):

**CLI** (inside the backend container — it loads `.env`, so keys are present):
```bash
ssh p100-guardian 'sudo docker exec openshorts-backend python -m explainer <cmd>'
# topics | script | clipfind | factcheck | assets | align | render | approve | schedule | cache | queue
```

**HTTP API / dashboard** — `openshorts.parkat.us` (Cloudflare Access), or curl
`localhost:8000/api/explainer/*` on the box. Stage routes return `{job_id}`; poll
`/api/explainer/jobs/{id}`. See `explainer_routes.py`.

Stage order: `script → clipfind → factcheck → assets → align → render → approve → schedule`.

## 4. Gotchas that cost real time

- **Costs money:** `script`, `clipfind`, `factcheck`, `assets` (TTS + Veo aid clips,
  ~$0.80/4s clip). **Free:** `align`, `render` (local GPU), and any cached aid.
  Aid generation is idempotent per file — never delete an `aid_*.mp4` casually.
- **Auto-captions are lossy.** YouTube VTT drops words and drifts. For accurate
  captions delete `output/explainer-<id>/clip*.words.json` before `align` so it
  falls back to whisper. `subtitles.transcribe_audio` uses **medium on cuda**; base
  hallucinates on real footage.
- **Verify quotes before building.** Timestamps in a hand-written brief are often
  approximate or wrong. Check the real transcript first — see `explainer/transcript.py`.
- **Clip cuts** are snapped to speech boundaries by `explainer/assets/snap.py`
  (whisper re-listen, capped drift). Disable with `EXPLAINER_SNAP=0`.
- **Aids loop** in the render — a 4-8s clip covering a longer beat used to hold a
  frozen frame. `aid.py` also sizes new clips (4/6/8s) to the beat.
- **Blurred-bars layout:** YouTube clips are kept full 16:9 and centered over a
  blurred copy — never crop them to 9:16.
- **Buffer publishing works.** Media is served un-gated at `media.parkat.us/m/<token>`.
  Any blocking call to Buffer must run off the event loop (`run_in_executor`) —
  Buffer fetches the media URL from this same server, so blocking deadlocks it and
  reports "Video could not be read from its URL".
- **Buffer free tier: 10 queued posts.** Each video = 3 posts (3 channels), so 3
  videos max in the queue.
- **Publish slots:** `BRAND["publish_times"]` (currently `04:00` + `17:00`
  America/Los_Angeles). `next_slot` walks day × time and skips taken slots.
- **Moods:** `brand.py → MOODS`. Put `"mood": "dark"` in `draft.script` for the
  investigative register (near-black palette, Charon @1.08). Default is unchanged.
