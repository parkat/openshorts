import React, { useEffect, useState } from 'react';
import { Plus, Loader2, Wand2, RotateCcw, CheckCircle2, AlertTriangle } from 'lucide-react';
import { explainerApi } from './api';
import useExplainerJob from './useExplainerJob';

// Manual topic add + kick off script generation. Sources are pasted as a small
// list of {type,url,in,out} rows (doc or youtube). Generating a script creates a
// Project + Draft, then hands off to the studio.
export default function TopicForm({ onProjectCreated }) {
  const [topics, setTopics] = useState([]);
  const [title, setTitle] = useState('');
  const [summary, setSummary] = useState('');
  const [sourcesText, setSourcesText] = useState('');
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState(null);

  const { job, start, running } = useExplainerJob((j) => {
    if (j.status === 'done' && j.result?.project_id) onProjectCreated?.(j.result.project_id);
    loadTopics();
  });

  const loadTopics = async () => {
    try { setTopics((await explainerApi.topics()).topics || []); } catch { /* ignore */ }
  };
  useEffect(() => { loadTopics(); }, []);

  const parseSources = () => {
    const t = sourcesText.trim();
    if (!t) return [];
    // Accept raw JSON, or one "url in out" per line (youtube).
    if (t.startsWith('[')) { try { return JSON.parse(t); } catch { throw new Error('sources JSON is invalid'); } }
    return t.split('\n').map((line) => {
      const [url, inS, outS] = line.trim().split(/\s+/);
      if (!url) return null;
      const src = { type: url.includes('youtu') ? 'youtube' : 'doc', url };
      if (inS !== undefined) src.in = parseFloat(inS);
      if (outS !== undefined) src.out = parseFloat(outS);
      return src;
    }).filter(Boolean);
  };

  const addTopic = async () => {
    setError(null);
    if (!title.trim()) { setError('title required'); return; }
    setAdding(true);
    try {
      let sources;
      try { sources = parseSources(); } catch (e) { setError(e.message); return; }
      await explainerApi.addTopic({ title, summary, sources });
      setTitle(''); setSummary(''); setSourcesText('');
      await loadTopics();
    } catch (e) {
      setError(e.message);
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="p-6 md:p-10 max-w-3xl mx-auto space-y-8">
      {/* Add topic */}
      <div className="glass-panel p-5 space-y-3">
        <h2 className="text-sm font-semibold text-zinc-300">New topic</h2>
        <input className="input-field w-full" placeholder="Title (the hook idea)" value={title} onChange={(e) => setTitle(e.target.value)} />
        <textarea className="input-field w-full h-16 resize-none" placeholder="Summary / angle (optional)" value={summary} onChange={(e) => setSummary(e.target.value)} />
        <textarea
          className="input-field w-full h-20 resize-none font-mono text-xs"
          placeholder={'Sources — one per line: "<youtube-url> <in> <out>"  or paste a JSON array'}
          value={sourcesText}
          onChange={(e) => setSourcesText(e.target.value)}
        />
        {error && <p className="text-xs text-red-300 flex items-center gap-1.5"><AlertTriangle size={13} /> {error}</p>}
        <button onClick={addTopic} disabled={adding} className="btn-primary flex items-center gap-2 !w-auto">
          {adding ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />} Add topic
        </button>
      </div>

      {/* Topics + generate script */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider">Topics ({topics.length})</h2>
          <button onClick={loadTopics} className="flex items-center gap-1.5 text-xs text-zinc-400 hover:text-white"><RotateCcw size={13} /> Refresh</button>
        </div>
        <div className="space-y-2">
          {topics.map((t) => (
            <div key={t.id} className="glass-panel p-4 flex items-center gap-3">
              <span className="text-xs font-mono text-zinc-600 shrink-0">#{t.id}</span>
              <div className="flex-1 min-w-0">
                <p className="text-white font-medium truncate">{t.title}</p>
                <p className="text-xs text-zinc-500">{t.origin} · {(t.sources || []).length} source(s) · {t.status}</p>
              </div>
              <button
                onClick={() => start(() => explainerApi.script(t.id))}
                disabled={running}
                className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors shrink-0 ${
                  running ? 'bg-white/5 text-zinc-600 cursor-not-allowed' : 'bg-cyan-500/15 text-cyan-300 hover:bg-cyan-500/25'
                }`}
              >
                {running && job?.stage === 'script' ? <Loader2 size={14} className="animate-spin" /> : <Wand2 size={14} />}
                Generate script
              </button>
            </div>
          ))}
          {topics.length === 0 && <p className="text-zinc-600 text-sm">No topics yet — add one above.</p>}
        </div>
      </div>

      {/* Script job status */}
      {job && (
        <div className="glass-panel p-4">
          {job.status === 'done' && job.result?.project_id ? (
            <p className="text-sm text-emerald-300 flex items-center gap-2"><CheckCircle2 size={15} /> Created project #{job.result.project_id} — opening…</p>
          ) : job.status === 'error' ? (
            <p className="text-sm text-red-300 flex items-center gap-2"><AlertTriangle size={15} /> {job.error}</p>
          ) : (
            <p className="text-sm text-zinc-400 flex items-center gap-2"><Loader2 size={15} className="animate-spin" /> Generating script…</p>
          )}
          {job.logs?.length > 0 && (
            <pre className="mt-2 max-h-40 overflow-y-auto custom-scrollbar bg-black/40 rounded-lg p-3 text-[11px] text-zinc-500 font-mono whitespace-pre-wrap">{job.logs.join('\n')}</pre>
          )}
        </div>
      )}
    </div>
  );
}
