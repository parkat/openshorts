import React, { useCallback, useEffect, useState } from 'react';
import {
  Scissors, RotateCcw, AlertTriangle, Search, Zap, Trash2, Film, Wand2,
} from 'lucide-react';
import { clipsApi, MOODS, EDITS, DEFAULT_EDIT, fmtClock } from './api';
import useClipsJob from './useClipsJob';
import JobLog from './JobLog';
import CandidateCard from './CandidateCard';
import ClipEditorModal from './ClipEditorModal';

// The clips lane: one long video in, many standalone Shorts out.
//
// Deliberately one page rather than a wizard. The lane's whole point is that you
// look at the proposed moments before spending anything on them, so the source
// list, the moments and their evidence all stay on screen together.
export default function ClipsTab() {
  const [url, setUrl] = useState('');
  const [limit, setLimit] = useState(0);
  const [mood, setMood] = useState('');
  const [edit, setEdit] = useState(DEFAULT_EDIT);
  const [sources, setSources] = useState([]);
  const [selected, setSelected] = useState(null);
  const [candidates, setCandidates] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState(null);

  const loadSources = useCallback(async () => {
    try {
      const d = await clipsApi.sources();
      setSources(d.sources || []);
      return d.sources || [];
    } catch (e) {
      setError(e.message);
      return [];
    }
  }, []);

  const loadCandidates = useCallback(async (sourceId) => {
    if (!sourceId) { setCandidates([]); return; }
    try {
      const d = await clipsApi.candidates({ source_id: sourceId });
      setCandidates(d.candidates || []);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    const list = await loadSources();
    // Land on the newest source when nothing is picked yet.
    const pick = selected ?? list[0]?.id ?? null;
    if (pick !== selected) setSelected(pick);
    await loadCandidates(pick);
    setLoading(false);
  }, [loadSources, loadCandidates, selected]);

  const { job, start, clear, running } = useClipsJob(async (finished) => {
    const list = await loadSources();
    // A fresh ingest/run creates the source — jump to it so its moments show.
    const newId = finished?.result?.source_id;
    const next = newId || selected || list[0]?.id || null;
    setSelected(next);
    await loadCandidates(next);
  });

  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, []);
  useEffect(() => { loadCandidates(selected); }, [selected, loadCandidates]);

  const run = (starter) => { setError(null); start(starter); };

  const findMoments = async () => {
    if (!url.trim()) { setError('paste a video URL first'); return; }
    // Ingest and scan are one action from here: a source with no moments found
    // is not something you can act on anyway.
    run(async () => {
      const res = await clipsApi.ingest(url.trim());
      return res;
    });
  };

  const runEverything = () => {
    if (!url.trim()) { setError('paste a video URL first'); return; }
    run(() => clipsApi.run(url.trim(), { limit: Number(limit) || 0, mood, edit }));
  };

  const scanSelected = () => {
    if (!selected) return;
    run(() => clipsApi.moments(selected, { limit: Number(limit) || 0 }));
  };

  const removeSource = async (id) => {
    await clipsApi.deleteSource(id);
    if (selected === id) setSelected(null);
    refresh();
  };

  const src = sources.find((s) => s.id === selected);

  return (
    <div className="h-full flex flex-col animate-[fadeIn_0.3s_ease-out]">
      {/* Header */}
      <div className="px-6 md:px-10 pt-6 pb-4 border-b border-white/5">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-violet-500/10 text-violet-400 flex items-center justify-center">
            <Scissors size={20} />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white leading-none">Clips</h1>
            <p className="text-xs text-zinc-500 mt-1">
              Mine one long video for the moments that stand alone.
            </p>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto custom-scrollbar p-6 md:p-10">
        <div className="max-w-4xl mx-auto">
          {/* New source */}
          <div className="glass-panel p-5 mb-6">
            <label className="block text-sm text-zinc-400 mb-2">Long-form video URL</label>
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://youtube.com/watch?v=..."
              className="input-field mb-4"
            />
            <div className="flex flex-wrap items-end gap-4">
              <div>
                <label className="block text-xs text-zinc-500 mb-1.5">Keep top</label>
                <select
                  value={limit}
                  onChange={(e) => setLimit(Number(e.target.value))}
                  className="input-field py-2 text-sm w-28"
                >
                  <option value={0}>all</option>
                  {[3, 5, 8, 12].map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs text-zinc-500 mb-1.5">Mood</label>
                <select
                  value={mood}
                  onChange={(e) => setMood(e.target.value)}
                  className="input-field py-2 text-sm w-32"
                >
                  {MOODS.map((m) => <option key={m} value={m}>{m || 'brand default'}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs text-zinc-500 mb-1.5">Edit</label>
                <select
                  value={edit}
                  onChange={(e) => setEdit(e.target.value)}
                  className="input-field py-2 text-sm w-44"
                >
                  {EDITS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>
              <div className="flex gap-2 ml-auto">
                <button
                  onClick={findMoments}
                  disabled={running}
                  className="flex items-center gap-2 text-sm px-4 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-200 disabled:opacity-40 transition-colors"
                >
                  <Search size={15} /> Ingest
                </button>
                <button
                  onClick={runEverything}
                  disabled={running}
                  className="btn-primary flex items-center gap-2 text-sm px-4 py-2 disabled:opacity-40"
                >
                  <Zap size={15} /> Run everything
                </button>
              </div>
            </div>
            <p className="text-[11px] text-zinc-600 mt-3 leading-relaxed">
              <strong>Ingest</strong> downloads the video once and builds its transcript — then scan
              it for moments below. <strong>Run everything</strong> chains ingest → moments → cut →
              render. Only the moment scan costs money; cutting and rendering are local.
              {edit === 'loop' ? (
                <>
                  {' '}Clips are cut as a <strong>loop</strong> by default: each one opens on its
                  payoff (⟲), then plays the run-up, ending on the frame the payoff began — so a
                  repeat runs straight back into the punchline with no seam. A moment with no
                  usable payoff falls back to linear on its own.
                </>
              ) : (
                <>
                  {' '}<strong>Linear</strong> plays each window straight through, instead of the
                  default payoff-first loop.
                </>
              )}
            </p>
          </div>

          {job && <JobLog job={job} onClose={clear} />}

          {error && (
            <div className="glass-panel p-4 flex items-center gap-3 text-red-300 text-sm mb-5">
              <AlertTriangle size={16} /> {error}
            </div>
          )}

          {/* Sources */}
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider">
              Sources {sources.length ? `(${sources.length})` : ''}
            </h2>
            <button
              onClick={refresh}
              className="flex items-center gap-2 text-xs text-zinc-400 hover:text-white transition-colors"
            >
              <RotateCcw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
            </button>
          </div>

          {sources.length === 0 ? (
            <div className="glass-panel p-8 text-center text-zinc-500 text-sm mb-6">
              No sources yet. Paste a long video URL above to get started.
            </div>
          ) : (
            <div className="space-y-2 mb-8">
              {sources.map((s) => (
                <div
                  key={s.id}
                  className={`glass-panel flex items-center gap-4 p-4 transition-colors ${
                    selected === s.id ? 'ring-1 ring-violet-500/40' : 'hover:bg-white/[0.06]'
                  }`}
                >
                  <button onClick={() => setSelected(s.id)} className="flex-1 min-w-0 text-left">
                    <p className="text-white font-medium truncate">{s.title || '(untitled)'}</p>
                    <p className="text-xs text-zinc-500 mt-0.5">
                      {s.uploader} · {fmtClock(s.duration_s)} · {s.candidates} candidate
                      {s.candidates === 1 ? '' : 's'} · transcript {s.transcript_source || '—'}
                    </p>
                  </button>
                  <button
                    onClick={() => removeSource(s.id)}
                    title="remove this source and its candidates"
                    className="text-zinc-600 hover:text-red-400 transition-colors shrink-0"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Candidates for the selected source */}
          {src && (
            <>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider">
                  Moments {candidates.length ? `(${candidates.length})` : ''}
                </h2>
                <button
                  onClick={scanSelected}
                  disabled={running}
                  className="flex items-center gap-2 text-xs px-3 py-1.5 rounded-lg bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 disabled:opacity-40 transition-colors"
                >
                  <Wand2 size={13} /> {candidates.length ? 'Re-scan' : 'Find moments'}
                </button>
              </div>

              {candidates.length === 0 ? (
                <div className="glass-panel p-8 text-center text-zinc-500 text-sm">
                  <Film size={22} className="mx-auto mb-2 opacity-40" />
                  Nothing scanned yet for “{src.title}”. Find moments to see what is in it.
                </div>
              ) : (
                <div className="space-y-3">
                  {candidates.map((c) => (
                    <CandidateCard
                      key={c.id}
                      candidate={c}
                      mood={mood}
                      edit={edit}
                      busy={running}
                      onRun={(starter) => run(starter)}
                      onChanged={() => loadCandidates(selected)}
                      onEdit={setEditing}
                    />
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {editing && (
        <ClipEditorModal
          candidate={editing}
          onClose={() => setEditing(null)}
          onChanged={() => loadCandidates(selected)}
        />
      )}
    </div>
  );
}
