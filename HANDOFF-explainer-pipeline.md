# HANDOFF — AI Explainer Shorts Pipeline (Build Brief)

**Repo:** `parkat/openshorts` (`feat/gpu-accel-and-split-mode`).
**Origin:** Cowork design session (2026-07-23) + on-box reconciliation (2026-07-22, this repo's dev session).
**Status:** design locked; §6–§8 now filled from the real environment; two architecture changes applied (OpenRouter-only, Claude-Code driver). Read §0 first — it supersedes the original brief where they conflict.

---

## 0. Reconciliation with current state (READ FIRST)

The original brief was written without box access. What's actually true now:

- **Publishing = Buffer, not Upload-Post.** The main Post flow was migrated to **Buffer** (`buffer_client.py`, `/api/buffer/*`, verified live to YouTube/TikTok/Instagram). Buffer needs a **hosted video URL** (no file upload) → we stood up **`media.parkat.us`** (tunnel ingress, **no Cloudflare Access**, tokenized `/m/<token>` route) to serve a clip publicly by unguessable token. **The explainer scheduler reuses Buffer + media.parkat.us.** Upload-Post remains only for the Thumbnail-YouTube and SaaS-Shorts flows.
- **One key: OpenRouter.** Replaces Gemini + Anthropic + ElevenLabs + Fal. OpenRouter now covers **LLM + image + video (Kling 9:16 / Veo / Sora, native audio) + TTS** on a single key. `openrouter_client.py` exists (chat done; image/video/TTS are Phase-1 dedicated endpoints). Key is server-side in `openshorts/.env` as `OPENROUTER`.
- **No Anthropic API spend.** parkat drives with a **Max-plan Claude Code session**, not paid API. So the reasoning-heavy steps (script polish, fact-check) run **either** via OpenRouter (headless/automated) **or** by the driving CC session at $0 — a `--provider` knob (see §3a).
- **Topic entry is manual-primary.** parkat will *usually bring the topic + document/YouTube sources himself.* The auto-radar (§4.1) is **secondary/optional** — build the manual path first; radar is a later convenience, not the spine.
- **Auth:** `openshorts.parkat.us` is behind **Cloudflare Access** (email allow-list). Server-side workers bypass it; anything the browser calls stays gated. `media.parkat.us` is intentionally un-gated (tokenized).
- **Serving:** dashboard is served as a **production build** via `vite preview` (not the dev server). Deploy = `docker restart openshorts-frontend` (rebuilds); backend picks up `app.py` on its own restart.
- **Datastore:** still in-memory jobs + JSON in `archive/` (`presets.json`, `media_tokens.json`). **SQLite is genuinely new** (sqlalchemy not installed) — the brief's call stands.

---

## 1. What we're building

A new **Explainer lane** on the OpenShorts stack: **30–45s, 9:16, faceless AI-education Shorts** in a **hype hot-take** voice, kept honest by an auto fact-check. Flow:

Topic (**manual by parkat**, radar optional) + pasted YouTube accent-clip URLs → script (hype, source-grounded) → **auto fact-check** → review gate 1 → assets (OpenRouter narration + trimmed accent clips + figures + OpenRouter b-roll + ducked CC0 music) → Remotion composite (NVENC) → review gate 2 → scheduler drips **1/day** → **Buffer** queue to YouTube Shorts + TikTok + Reels.

New lane, parallel to the existing Clip Generator and AI Shorts lanes — share utilities, don't repurpose.

---

## 2. Locked decisions

| Dimension | Decision |
|---|---|
| Flagship lane | Original AI explainer, accented with user-supplied YouTube clips |
| Length / shots | 30–45s, single idea, ~5–9 shots |
| Tone | Hype hot-take, kept honest by fact-check |
| Narration | OpenRouter TTS; swappable voice, A/B by retention |
| Visual spine | Composite: slides, motion graphics, paper figures, accent clips, AI b-roll — auto-selected per shot |
| Accent clips | parkat pastes URLs + in/out timestamps (rights-curation gate) |
| Fair-use | Reach-first + generous transformative guardrails, enforced automatically (§5) |
| Attribution | On-screen "via <source>" + description credits |
| Music | **CC0 local library** (Pixabay-License/FMA/Jamendo seed), sidechain-ducked. NOT YouTube Audio Library (not TikTok/Reels-safe) |
| Accuracy | Auto fact-check before render → flags in review queue |
| Models | **OpenRouter, model-ID = knob.** Draft `google/gemini-3.5-flash`; polish+factcheck `anthropic/claude-sonnet-5` (or the CC session); image `google/gemini-3.1-flash-image`; video Kling-9:16/Veo; TTS OpenRouter `/audio/speech` |
| Control surface | **Two drivers on shared SQLite state:** the `openshorts.parkat.us` dashboard **and** a Claude Code session via an `explainer` CLI (§3a) |
| Cadence / platforms | 1/day → **Buffer** queue → YouTube Shorts + TikTok + Instagram Reels |
| Datastore | **SQLite (SQLAlchemy)** for the durable review queue/state |

---

## 3. Target architecture (repo-relative)

Existing stack: Python 3.11 **FastAPI** (`app.py`, `main.py`, `editor.py`, `hooks.py`, `subtitles.py` [NVENC], `translate.py`, `s3_uploader.py`, `saasshorts.py`, **`buffer_client.py`**, **`openrouter_client.py`**), React/Vite/Tailwind `dashboard/` (prod-build served), Remotion `remotion/` + `render-service/`, Docker (`docker-compose.yml` + `docker-compose.gpu.yml`), NVENC on this branch.

**New backend modules (`explainer/` package):**

| Path | Responsibility |
|---|---|
| `explainer/radar/` | *(Phase 3, optional)* source adapters (arxiv, hf_papers, pwc, blogs, reddit_hn, channels) + `rank.py`/`dedup.py` |
| `explainer/script.py` | Model router (via `openrouter_client`) + hype templates → **shot list** (`hook → setup → the thing → why it matters → button`), each factual line tagged with a source pointer |
| `explainer/factcheck.py` | Atomic claims → verify vs source doc → `supported / unsupported / overstated` flags |
| `explainer/assets/tts.py` | OpenRouter `/audio/speech` narration; voice A/B hook |
| `explainer/assets/clips.py` | `yt-dlp` fetch pasted URLs → trim → **guardrails (§5)** |
| `explainer/assets/figures.py` | source figures / page screenshots |
| `explainer/assets/broll.py` | OpenRouter video (Kling 9:16 / Veo) + Ken Burns fallback |
| `explainer/assets/music.py` | pick from local CC0 library + sidechain duck (ffmpeg) |
| `explainer/align.py` | faster-whisper word timestamps → captions + shot timing (reuse `subtitles.py`) |
| `explainer/render.py` | scene-list JSON → `render-service` → NVENC export |
| `explainer/schedule.py` | 1/day drip → **`buffer_client` + media.parkat.us** → 3 platforms; description builder w/ credits |
| `explainer/cli.py` | **CLI driver (§3a)** |
| `store.py` | SQLite (SQLAlchemy): `topics, projects, drafts, clips, schedule, posts, voices` (+ `media_tokens` if migrating off JSON) |

**New API endpoints (extend `app.py`, async-job convention):**
`GET /api/explainer/topics` · `POST /api/explainer/topics` (manual add: title + doc/YT sources) · `POST /api/explainer/topics/{id}/approve` (accent clip URLs+timestamps) · `POST /api/explainer/script` · `POST /api/explainer/factcheck` · `POST /api/explainer/render` · `GET /api/explainer/queue` · `POST /api/explainer/drafts/{id}/approve` · `GET/POST /api/explainer/schedule`.

**Remotion:** new `ExplainerShort` composition, data-driven scene-list: `SlideScene`, `MotionTextScene`, `FigureScene`, `AccentClipScene` (attribution overlay), `BrollScene` + global `Captions` + `MusicBed`. Keep it data-driven so shot types need no redeploy. Reuse the fast NVENC subtitle-burn path.

**Dashboard:** new tabs — **Topic** (manual add + paste sources; radar list if/when built), **Explainer Studio** (script/shot-list editor, fact-check flags, voice picker), **Review Queue** (previews, approve/re-render), **Scheduler** (calendar, per-platform slots, publish log). Reuse `ResultCard`, `ScheduleWeekModal`, `ScriptChatModal`, `BatchBar`.

### 3a. Two drivers (dashboard + Claude Code)

Both operate on the **same SQLite state**:

1. **Dashboard** — the tabs above (browser, behind Access).
2. **`explainer` CLI** — a Claude Code session (parkat's **Max plan**) drives the pipeline and can do the smart steps itself:
   `python -m explainer topics|script|factcheck|assets|render|queue|approve|schedule …`
   - LLM steps take `--provider openrouter` (headless/automated, the `worker` default) **or** `--provider manual` (a CC session supplies script polish / fact-check output → written back to SQLite; **$0 API**).
   - So the daily `worker` runs hands-off on OpenRouter, but when parkat is in the loop via Claude Code, the reasoning-heavy work is free.

---

## 4. Pipeline stages

1. **Topic** — *manual add* (parkat: title + doc/YT sources) is the primary path; radar (§ optional) can also surface `Topic{title, summary, source_url, score, angle}`.
2. **Approve** — greenlight + paste accent-clip URLs + in/out timestamps.
3. **Script** — model knob → 30–45s hype shot list; every factual line carries a source pointer.
4. **Fact-check** — claim extraction + source verification → flags.
5. **Review gate 1** — edit script, resolve flags, confirm clips, pick voice.
6. **Assets (parallel)** — TTS · fetch+trim clips (guardrails) · figures · b-roll · music bed.
7. **Align** — whisper word timestamps → captions + shot timing.
8. **Compose** — Remotion assembles scenes + captions + attribution + ducked music.
9. **Render** — NVENC 9:16 on the GPU.
10. **Review gate 2** — final approve / quick re-render.
11. **Schedule + publish** — 1/day best slot → **Buffer** queue to 3 platforms; auto description w/ credits.
12. **Backup + analytics** — (S3 optional) log per-post metrics for the Phase-3 retention loop.

---

## 5. Fair-use guardrails (`assets/clips.py` + render) — enforce automatically, overridable in gate 1

- **Narration-dominant:** ≥ ~60% runtime original narration/visuals; warn if an accent-clip run exceeds it.
- **Excerpt caps:** soft ~15s/clip; **hard-block** >30s uninterrupted or a clip longer than the narration (surface as a fixable flag, not a silent drop).
- **Duck clip audio** under narration by default.
- **Attribution:** on-screen "via <source>" while a clip plays + source links in the description.
- **Provenance log:** persist every accent clip's URL, channel, timestamps, fetch date in `clips` (dispute-ready).
- **No music laundering:** music only from the CC0 bed; clip audio stays short + ducked.

(Engineering guardrails, not legal advice — defensible-by-construction while staying reach-first.)

---

## 6. COMPUTE BOX — filled

- **Reach:** SSH-only via jump — Proxmox node `192.168.68.59` → `pct exec 104` → `ssh -i /etc/nvr-creds/gpu-box.key pt@192.168.68.72`. Repo at **`/home/pt/openshorts`**.
- **GPUs:** Tesla **P100 16GB** (GPU 0) + **RTX 2060 SUPER 8GB** (GPU 1), driver **535.309.01**. `docker-compose.gpu.yml` pins the **backend to the 2060 SUPER** by UUID; P100 stays free for the NVR. *(requirements pins `cu126`; driver 535 works — confirm torch imports CUDA at runtime.)*
- **Docker 29.6.2 / Compose v5.3.1, NVIDIA runtime present.** NVENC verified in-container.
- **Deploy:** `docker compose -f docker-compose.yml -f docker-compose.gpu.yml`; backend `:8000`, frontend `vite preview` `:5175→5173` (prod build), renderer `:3100`. Restart the relevant container to ship.
- **Persistence (bind mounts):** `./output` (renders/clips), `./archive` (durable JSON; **put `openshorts.db` here**). Add a **`worker`** service for the scheduler/optional-radar (no GPU needed).

## 7. WEBSITE / DASHBOARD ENV — filled

- **Public:** `openshorts.parkat.us` (+ new **`media.parkat.us`** for public tokenized clip hosting).
- **Reverse proxy/TLS:** **Cloudflare Tunnel** (`cloudflared` on CT100), not nginx/Caddy.
- **Auth:** **Cloudflare Access** email allow-list in front of `openshorts.parkat.us`. Workers/CLI run server-side and bypass it. `media.parkat.us` is un-gated (tokenized).
- **Deploy dashboard changes:** edit `dashboard/src/…` → `docker restart openshorts-frontend` (runs `vite build && vite preview`).

## 8. SECRETS — filled

- **Server-side `openshorts/.env` (mode 644 so the container can read it):**
  - **`OPENROUTER`** — the one key for LLM + image + video + TTS. ✅ installed + verified (credits live).
  - **`BUFFER`** — publish key; the `/api/buffer/*` endpoints fall back to it when no `X-Buffer-Key` header (so the headless scheduler posts). ✅ installed + verified.
  - `AWS_*` present but **blank (S3 OFF)** — we host via `media.parkat.us`, not S3. Fill only if you want S3 backup.
- **No** `GEMINI/ANTHROPIC/ELEVENLABS/FAL` keys — collapsed into OpenRouter. Browser-side keys for the *other* lanes stay in localStorage (unchanged).
- **Source lists (defaults; parkat mostly supplies topics manually):**
  - arXiv: `cs.CL, cs.LG, cs.AI, cs.CV, stat.ML` · daily: HuggingFace Papers, Papers with Code.
  - YT/podcasts: Two Minute Papers, Yannic Kilcher, bycloud, AI Explained, ML Street Talk, Lex Fridman, Dwarkesh Patel, Latent Space.
  - Subreddits: r/MachineLearning, r/LocalLLaMA, r/singularity, r/artificial, r/OpenAI. + HN front page (AI keywords).
  - Music: local CC0 library seeded from **Pixabay Music** (Pixabay License, no attribution, multi-platform safe), FMA, Jamendo.
  - Brand (name/logo/colors/font/intro-outro) + best daily publish time per platform: **still needed from parkat.**

---

## 9. Build roadmap

**Phase 0 — Foundations.** SQLite `store.py` + `worker` service + `explainer` CLI skeleton; config wiring (OpenRouter/Buffer already in `.env`). *Exit: DB read/write persists across restarts; CLI lists an (empty) queue; container builds with GPU.*

**Phase 1 — Manual vertical slice.** Manual topic → `script.py` (OpenRouter or CC) → pasted clip URLs → Remotion composite (basic scenes) + captions → Review Queue → **Buffer** to one platform. *Exit: a real 30–45s Short renders on the box and lands in the Buffer queue.*

**Phase 2 — Automation + guardrails.** fact-check → voice A/B → attribution + music duck → guardrails (§5) → 1/day scheduler → Buffer to all 3. *Exit: manual topic → auto-build → review → daily auto-publish, hands-off after parkat's two approvals.*

**Phase 3 — Polish + scale.** Optional radar (2–3 sources first), richer motion-graphics, b-roll where it helps, thumbnails/titles (reuse `thumbnail.py`), retention loop that A/B-picks voices/hooks from analytics.

---

## 10. Acceptance gates

- **P0:** compose builds with GPU; SQLite persists; `python -m explainer queue` runs.
- **P1:** one explainer renders 9:16 with synced captions + ≥1 pasted accent clip under narration; appears in Review Queue; queues to one platform via Buffer.
- **P2:** fact-check flags a deliberately-wrong claim; guardrails block an over-long clip; approved draft auto-queues to all 3 on the daily slot; provenance logged.
- **P3:** thumbnails/titles auto-gen; analytics logged; a documented rule picks the next voice/hook variant.

---

## 11. Open items / notes

- **Video is the credit driver** on OpenRouter (cents-to-dimes/clip vs ~free text/image). $50 covers heavy text/image + moderate video; guardrails + b-roll-only-where-it-helps keep it sane.
- **Keep the Remotion scene-list data-driven** so new shot types don't need a redeploy.
- Companion design spec `pureclips-explainer-pipeline-design.md` exists — ask parkat if the fuller rationale is needed.
- Parked: weekly long-form "everything in AI this week" compilation from the week's Shorts.
