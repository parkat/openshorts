import React, { useCallback, useEffect, useState } from 'react';
import {
  X, Type, Sparkles, Loader2, RotateCcw, Check, AlertTriangle, History, Send,
} from 'lucide-react';
import SubtitleModal from '../SubtitleModal';
import HookModal from '../HookModal';
import { clipsApi, getApiUrl } from './api';

// The original project's clip editor, pointed at a clips-lane candidate.
//
// Those tools address a clip as (job_id, clip_index) and read the job's metadata
// from disk. The backend writes a metadata shim for the candidate (see
// clips/editor.py), so SubtitleModal and HookModal are reused unmodified here —
// no fork, and a fix to either one lands in both places at once.
//
// One deliberate difference: the modals can also render in-browser and hand back
// a blob URL. Their live preview is kept — that is the useful half — but the
// commit always goes through the server-side ffmpeg path. A blob exists only in
// this tab, so a clip edited that way could be watched and never published, and
// this lane exists to publish.
export default function ClipEditorModal({ candidate, onClose, onChanged }) {
  const [state, setState] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [pane, setPane] = useState(null);       // 'subtitles' | 'hook'
  const [caption, setCaption] = useState(candidate.caption || '');
  const [title, setTitle] = useState(candidate.title || '');
  const [savedCopy, setSavedCopy] = useState(true);

  const load = useCallback(async () => {
    try {
      setState(await clipsApi.openEditor(candidate.id));
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, [candidate.id]);

  useEffect(() => { load(); }, [load]);

  const filename = state?.filename || '';
  const videoUrl = filename
    ? getApiUrl(`/videos/${state.job_id}/${filename}?v=${encodeURIComponent(filename)}`)
    : '';
  // A Remotion render already has the words burned in; burning a second set on
  // top would double them. The candidate is re-rendered clean first.
  const hasBurnedCaptions = /^remotion_/.test(filename);

  const run = async (label, fn) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
      await load();
      onChanged?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  // Both editor endpoints return the new filename; adopting it makes that file
  // the candidate's render, so the card, the download and any post follow the edit.
  const applyEdit = async (path, body) => {
    const res = await fetch(getApiUrl(path), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id: state.job_id, clip_index: 0,
        input_filename: filename, ...body }),
    });
    if (!res.ok) {
      let msg = `${res.status}`;
      try { msg = (await res.json()).detail || msg; } catch { /* text body */ }
      throw new Error(msg);
    }
    const data = await res.json();
    if (!data.new_video_url) throw new Error('the editor returned no file');
    await clipsApi.adopt(candidate.id, data.new_video_url.split('/').pop());
    setPane(null);
  };

  const burnSubtitles = (o) => run('subtitles', async () => {
    // The modal's text pane can rewrite the words. Those live in the Remotion
    // preview config, but the burn regenerates its SRT from the candidate's
    // stored captions — so persist any edit first, or the file would keep the
    // old words while the preview showed the new ones.
    const edited = o.remotion?.captions;
    if (edited?.length) {
      await clipsApi.update(candidate.id, { captions: edited });
      await clipsApi.openEditor(candidate.id);
    }
    await applyEdit('/api/subtitle', {
      position: o.position, margin_v: o.margin_v, font_size: o.fontSize,
      font_name: o.fontName, font_color: o.fontColor, border_color: o.borderColor,
      border_width: o.borderWidth, bg_color: o.bgColor, bg_opacity: o.bgOpacity,
    });
  });

  const burnHook = (h) => run('hook', () => applyEdit('/api/hook', {
    text: h.text, position: h.position, size: h.size,
  }));

  const saveCopy = () => run('copy', async () => {
    await clipsApi.update(candidate.id, { title, caption });
    setSavedCopy(true);
  });

  const rerenderClean = () => run('rerender', async () => {
    const { job_id: jid } = await clipsApi.render(candidate.id, { captions: false });
    // The render is a queued backend job; wait it out rather than leaving the
    // editor pointing at the file it is about to replace.
    for (;;) {
      const job = await clipsApi.job(jid);
      if (job.status === 'done') return;
      if (job.status === 'error') throw new Error(job.error || 'render failed');
      await new Promise((r) => { setTimeout(r, 1500); });
    }
  });

  const queueToBuffer = () => run('publish', async () => {
    const res = await clipsApi.publish(candidate.id);
    const okCount = (res.results || []).filter((r) => r.ok).length;
    if (!okCount) {
      throw new Error((res.results || [])[0]?.error || 'Buffer accepted nothing');
    }
    setError(null);
  });

  const btn = 'flex items-center gap-2 text-xs px-3 py-2 rounded-lg transition-colors disabled:opacity-40';

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-[fadeIn_0.2s_ease-out]">
      <div className="bg-[#121214] border border-white/10 rounded-2xl w-full max-w-5xl max-h-[92vh] overflow-y-auto custom-scrollbar shadow-2xl relative">
        <button onClick={onClose} className="absolute top-4 right-4 text-zinc-500 hover:text-white z-10">
          <X size={20} />
        </button>

        <div className="p-6">
          <p className="text-[11px] font-mono text-zinc-600">#{candidate.id}</p>
          <h2 className="text-lg font-bold text-white leading-snug pr-10">
            {candidate.title || '(untitled)'}
          </h2>
          <p className="text-xs text-zinc-500 mt-1">
            Editing <span className="font-mono text-zinc-400">{filename || '—'}</span>
          </p>

          {error && (
            <div className="glass-panel p-3 flex items-start gap-2 text-red-300 text-xs mt-4">
              <AlertTriangle size={14} className="shrink-0 mt-0.5" /> {error}
            </div>
          )}

          <div className="flex flex-col lg:flex-row gap-6 mt-5">
            {/* Preview */}
            <div className="lg:w-[260px] shrink-0">
              {videoUrl ? (
                <video
                  key={filename}
                  src={videoUrl}
                  controls
                  className="w-full rounded-xl bg-black border border-white/5"
                />
              ) : (
                <div className="aspect-[9/16] rounded-xl bg-black/40 border border-white/5 flex items-center justify-center text-zinc-600 text-xs">
                  no render yet
                </div>
              )}
            </div>

            <div className="flex-1 min-w-0 space-y-5">
              {/* Tools */}
              <div>
                <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">
                  Edit the video
                </h3>
                {hasBurnedCaptions && (
                  <div className="glass-panel p-3 text-[11px] text-amber-200/90 leading-relaxed mb-3">
                    This render has captions burned in by Remotion. Burning a second
                    set would put two lines of words on the same frame — re-render it
                    clean first, then style the subtitles here.
                    <button
                      onClick={rerenderClean}
                      disabled={!!busy}
                      className={`${btn} bg-amber-500/15 hover:bg-amber-500/25 text-amber-200 mt-2`}
                    >
                      {busy === 'rerender'
                        ? <Loader2 size={13} className="animate-spin" />
                        : <RotateCcw size={13} />}
                      Re-render without captions
                    </button>
                  </div>
                )}
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => setPane('subtitles')}
                    disabled={!!busy || !filename}
                    className={`${btn} bg-white/5 hover:bg-white/10 text-zinc-200`}
                  >
                    {busy === 'subtitles'
                      ? <Loader2 size={13} className="animate-spin" />
                      : <Type size={13} />}
                    Subtitles
                  </button>
                  <button
                    onClick={() => setPane('hook')}
                    disabled={!!busy || !filename}
                    className={`${btn} bg-white/5 hover:bg-white/10 text-zinc-200`}
                  >
                    <Sparkles size={13} /> Text overlay
                  </button>
                </div>
              </div>

              {/* Publish copy */}
              <div>
                <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">
                  What gets posted
                </h3>
                <input
                  value={title}
                  onChange={(e) => { setTitle(e.target.value); setSavedCopy(false); }}
                  placeholder="Publish title"
                  className="input-field text-sm mb-2"
                />
                <textarea
                  value={caption}
                  onChange={(e) => { setCaption(e.target.value); setSavedCopy(false); }}
                  rows={4}
                  placeholder={candidate.hook
                    ? `Leave empty to post:\n\n${candidate.hook}\n\n${candidate.title || ''}`.trim()
                    : 'Leave empty to post the title'}
                  className="input-field text-sm resize-y"
                />
                <div className="flex items-center gap-3 mt-2">
                  <button
                    onClick={saveCopy}
                    disabled={!!busy || savedCopy}
                    className={`${btn} bg-white/5 hover:bg-white/10 text-zinc-200`}
                  >
                    {busy === 'copy'
                      ? <Loader2 size={13} className="animate-spin" />
                      : <Check size={13} />}
                    {savedCopy ? 'Saved' : 'Save copy'}
                  </button>
                  <button
                    onClick={queueToBuffer}
                    disabled={!!busy || !filename}
                    className={`${btn} bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300`}
                    title="queue this clip into the shared publishing calendar"
                  >
                    {busy === 'publish'
                      ? <Loader2 size={13} className="animate-spin" />
                      : <Send size={13} />}
                    Queue to Buffer
                  </button>
                </div>
              </div>

              {/* Version history */}
              {(state?.history || []).length > 1 && (
                <div>
                  <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                    <History size={13} /> Versions
                  </h3>
                  <div className="space-y-1.5">
                    {state.history.map((h) => (
                      <div
                        key={h.filename}
                        className={`flex items-center gap-3 px-3 py-2 rounded-lg text-xs ${
                          h.current ? 'bg-violet-500/10 text-violet-200' : 'bg-white/[0.03] text-zinc-400'
                        }`}
                      >
                        <span className="font-mono truncate flex-1">{h.filename}</span>
                        <span className="text-zinc-600 shrink-0">
                          {(h.bytes / 1048576).toFixed(1)} MB
                        </span>
                        {h.current ? (
                          <span className="shrink-0">current</span>
                        ) : (
                          <button
                            onClick={() => run('revert', () => clipsApi.adopt(candidate.id, h.filename))}
                            disabled={!!busy}
                            className="shrink-0 text-zinc-500 hover:text-white transition-colors"
                            title="make this the current version"
                          >
                            use
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                  <p className="text-[11px] text-zinc-600 mt-2 leading-relaxed">
                    Every edit writes a new file rather than overwriting one, so
                    stepping back to any earlier version costs nothing.
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      <SubtitleModal
        isOpen={pane === 'subtitles'}
        onClose={() => setPane(null)}
        onGenerate={burnSubtitles}
        isProcessing={busy === 'subtitles'}
        videoUrl={videoUrl}
        jobId={state?.job_id}
        clipIndex={0}
        existingHook={candidate.hook}
      />
      <HookModal
        isOpen={pane === 'hook'}
        onClose={() => setPane(null)}
        onGenerate={burnHook}
        isProcessing={busy === 'hook'}
        videoUrl={videoUrl}
        initialText={candidate.hook || candidate.title || ''}
        durationInSeconds={state?.duration_s || candidate.seconds}
      />
    </div>
  );
}
