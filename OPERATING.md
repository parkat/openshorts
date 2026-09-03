# OPERATING.md — driving the deployment

How to reach and operate gpu-pc from any machine (desktop, laptop, a fresh
Claude Code session). Written 2026-07-24.

---

## 1. Reaching the box

The box is **`gpu-pc`** (`192.168.68.72`), user **`pt`**. It runs the
whole stack in Docker. **It gets wiped periodically — treat it as disposable.**

> ⚠️ **Only `./archive` has actually proved durable.** The Aug 19 2026 reprovision
> kept `archive/` (the SQLite store, media tokens, presets) and took **`output/`
> with it** — every `explainer-<id>/` render, and the `media.parkat.us` tokens
> pointing at them, were lost while the DB still listed the projects as reviewable.
> `cache/` (the paid-asset content cache, `EXPLAINER_CACHE`) sits in the same
> repo dir and survived that round, but it is exposed to the same risk. Treat a
> finished render as gone unless it has been published or copied into `archive/`.
>
> A *second*, self-inflicted cause was fixed on 2026-09-02: `cleanup_jobs()` in
> `app.py` rmtree'd anything under `output/` older than `JOB_RETENTION_SECONDS`
> (24h), including `explainer-*` and `clips-*`. Those prefixes are now exempt
> (`_is_purgeable`) — their retention is a lane decision, not a clock. A render
> that vanishes now points at a wipe, not the purge. Candidates report
> `has_render` from the filesystem so the dashboard says so instead of showing a
> dead player.

Access is over **Tailscale**, via a subnet router on persistent Proxmox
infrastructure (so the box itself needs nothing installed):

```
laptop ─tailscale─→ lxc-100 "hub" (100.108.154.84, advertises 192.168.68.0/22)
                          └─→ gpu-pc 192.168.68.72
```

Suggested `~/.ssh/config` (key name will vary per machine):

```
Host gpu-pc-direct          # PRIMARY — direct, via the subnet route
    HostName 192.168.68.72
    User pt
    IdentityFile ~/.ssh/openshorts_box

Host hub                    # lxc-100, the Proxmox subnet router
    HostName 100.108.154.84
    User root
    IdentityFile ~/.ssh/openshorts_box

Host gpu-pc-via-hub         # FALLBACK — survives a box wipe (see below)
    HostName 192.168.68.72
    User pt
    ProxyJump hub
    IdentityFile ~/.ssh/openshorts_box
```

Canonical names come from `homelab/NAMING.md`. On Parker's desktop the same box
is reached as `gpu-pc` (hopping via `pve-r340`) — legacy aliases `p100-guardian`,
`gpu-box` and `comfy-box` still resolve there during the migration.

**After a box wipe** `~/.ssh/authorized_keys` on the box is gone with it. lxc-100
holds its own credential (`/etc/hub/ssh/id_ed25519`, trusted as `hub-agent@home`)
that the box's provisioning restores, so `gpu-pc-via-hub` is the recovery path. Any
new personal key must be added to the box's provisioning or it only survives until
the next wipe.

Proxmox host itself: `pve-r340` — reach it at **`192.168.71.59`**, not `.68.59`
(an HP printer squats that address). Containers: `lxc-100` (`hub` — cloudflared +
tailscale), `lxc-104` (`nvr`, holds `/etc/nvr-creds/gpu-box.key`).

## 2. Deploying changes

The repo lives at `/home/pt/openshorts` on the box. Ship by checking files out of
origin — **do not edit on the box**.

```bash
ssh gpu-pc 'cd ~/openshorts && git fetch -q origin \
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
| `remotion/src/**`, `render-service/src/**` | `sudo docker compose -f docker-compose.yml -f docker-compose.gpu.yml build renderer && ... up -d renderer` |

Renderer rebuilds take several minutes — run them in the background and wait on the
container being recreated, not on the command returning.

## 3. Driving the pipeline

Two equivalent drivers over the same SQLite state (`archive/openshorts.db`):

**CLI** (inside the backend container — it loads `.env`, so keys are present):
```bash
ssh gpu-pc 'sudo docker exec openshorts-backend python -m explainer <cmd>'
# topics | script | clipfind | factcheck | assets | align | render | approve | schedule | cache | queue
```

The **clips lane** (source-first: one long video -> many Shorts) has its own driver
over the same store:
```bash
ssh gpu-pc 'sudo docker exec openshorts-backend python -m clips <cmd>'
# ingest | moments | cut | render | run | sources | queue | show | approve | reject
```
Only `moments` spends (one LLM call per ~40k chars of transcript). `ingest` costs one
download; `cut` and `render` are local and free. `run --url ...` chains the lot.

**Cuts are payoff-first loops by default** (`clips/cut.py:DEFAULT_EDIT`). Each clip is
a *rotation* of its window about the payoff: punchline first, then the run-up, ending
on the frame the punchline began — so the platform's auto-repeat wraps into continuous
speech. All three boundaries (open, the punchline→run-up cut, and the wrap) are aligned
to whole sentences by one whisper pass in `plan_window`. A moment with no usable payoff
falls back to `linear` and logs why. Force either with `--edit linear|loop`.

Caveat: whisper's punctuation shifts with how much audio it is given, so re-cutting the
same candidate can pick a different (still sentence-aligned) split.

### Publishing (both lanes, one calendar)

`publishing.py` + the dashboard's **Publishing** tab own everything about what
goes out. Defaults come from `brand.py`; only what you change in the UI is stored
(the `settings` table), so an untouched install behaves exactly like the brand file.

```bash
ssh gpu-pc 'curl -s localhost:8000/api/publishing/status | python3 -m json.tool'
```

- **Slots are exclusive across lanes.** Both lanes draw from the same
  `publish_times`, so nothing double-books a minute. `per_day` caps how many of a
  day's slots one lane may take.
- **`paused`** is the master hold — stops both drips without stopping anything
  else on the box.
- **Clips is hand-queued by default** (`lanes.clips.auto = false`); explainer
  keeps its 1/day auto-drip. The worker ticks both every `SCHEDULER_INTERVAL`.
- **A dead Buffer token is the usual cause** of anything here failing, and it
  fails silently everywhere else — the tab's first panel says so in words. Paste
  a new one into that panel: it is checked against Buffer before it is stored,
  lands server-side (where the worker can reach it, unlike the Settings tab's
  browser-held key), and takes effect with no restart. `BUFFER` in `.env` remains
  the fallback.
- **Hashtags come in two kinds** (`hashtags.py`). The always-on per-platform tags
  (`#shorts` / `#fyp` / `#reels`) are settings, appended at post time to both
  lanes — change them once and every future post re-composes. Tags describing a
  particular clip are generated per clip in its editor and stored on the row.
  Content is trimmed to fit the per-platform cap; the routing tags never are.

### Clip editor (clips lane)

The original lane's subtitle / text-overlay tools work on clips candidates via a
metadata shim (`clips/editor.py`) — no forked UI. Edits are additive files, so
the output dir is the undo history.

**A Remotion render already has captions burned in.** Burning a second set doubles
them, so re-render clean first (`with_captions=False`, offered in the editor)
before styling subtitles.

**HTTP API / dashboard** — `openshorts.parkat.us` (Cloudflare Access), or curl
`localhost:8000/api/explainer/*` on the box. Stage routes return `{job_id}`; poll
`/api/explainer/jobs/{id}`. See `explainer_routes.py`.

Stage order: `script → clipfind → factcheck → assets → align → render → approve → schedule`.

## 4. Gotchas that cost real time

- **Costs money:** `script`, `clipfind`, `factcheck`, `assets` (TTS, plus aid visuals
  in `--aid-mode video`). **Free:** `align`, `render` (local GPU), and any cached aid.
  Generation is idempotent per output file.
- **Aid visuals default to motion graphics** (`--aid-mode motion`, env
  `EXPLAINER_AID_MODE`). The LLM authors a Remotion component per aid shot: **~$0.04**
  and seconds (measured, claude-sonnet-5, one clean attempt), versus ~$0.80/4s clip and
  minutes of polling for `--aid-mode video` — and a spoken aid is a 3-clip montage, so
  that's ~$0.04 against ~$2.40 for the same beat. Lands
  as `aid_<shot>.jsx` (readable source) + `aid_<shot>.js` (compiled) in the project
  dir. **Both are hand-editable** — tweak the `.jsx`, delete the `.js`, re-run `assets`
  to recompile, then `render`; no LLM spend. In `video` mode, still never delete an
  `aid_*.mp4` casually.
- **A motion aid follows the mood.** It draws only from `theme`, so switching
  `draft.script["mood"]` and re-running `render` alone re-colours every aid. Baked
  `aid_*.mp4` clips cannot do this — they need regenerating. The compile gate rejects
  hardcoded hex colours precisely to keep that true.
- **Generated aid code is gated** by the render-service: `POST /aid/compile` (denylist
  + esbuild transform) and `POST /aid/probe` (renders 3 frames, rejects blank or
  non-animating output). Skip probing with `EXPLAINER_AID_PROBE=0` when iterating;
  retries via `EXPLAINER_AID_ATTEMPTS` (default 3).
- **Auto-captions are lossy.** YouTube VTT drops words and drifts. For accurate
  captions delete `output/explainer-<id>/clip*.words.json` before `align` so it
  falls back to whisper. `subtitles.transcribe_audio` uses **medium on cuda**; base
  hallucinates on real footage.
- **Verify quotes before building.** Timestamps in a hand-written brief are often
  approximate or wrong. Check the real transcript first — see `explainer/transcript.py`.
- **Clip cuts** are snapped to speech boundaries by `explainer/assets/snap.py`
  (whisper re-listen, capped drift). Disable with `EXPLAINER_SNAP=0`.
- **`--aid-mode video` clips still freeze on a long beat.** `Scenes.tsx` passes `loop`
  to `OffthreadVideo`, but Remotion 4.0.496 has no such prop — it is silently dropped,
  so a 4-8s clip covering a longer beat holds its last frame. `aid.py` sizing (4/6/8s)
  only narrows the gap. Motion aids have no such problem: they're a function of
  `progress`, so they fill whatever beat `align` computes, exactly.
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
