import React, { useEffect, useState } from 'react';
import { RotateCcw, Trash2, Database, Search } from 'lucide-react';
import { explainerApi, humanBytes } from './api';

const KINDS = ['', 'video', 'image', 'transcript', 'youtube', 'clip', 'svg', 'audio'];

const KIND_TINT = {
  video: 'bg-violet-500/15 text-violet-300',
  image: 'bg-pink-500/15 text-pink-300',
  transcript: 'bg-blue-500/15 text-blue-300',
  youtube: 'bg-red-500/15 text-red-300',
  clip: 'bg-cyan-500/15 text-cyan-300',
  svg: 'bg-emerald-500/15 text-emerald-300',
  audio: 'bg-amber-500/15 text-amber-300',
};

export default function CacheExplorer() {
  const [stats, setStats] = useState(null);
  const [items, setItems] = useState([]);
  const [kind, setKind] = useState('');
  const [text, setText] = useState('');
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [st, it] = await Promise.all([
        explainerApi.cacheStats(),
        explainerApi.cacheItems({ kind, text }),
      ]);
      setStats(st);
      setItems(it.items || []);
    } catch { /* ignore */ } finally { setLoading(false); }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [kind]);

  const del = async (id) => {
    if (!window.confirm('Delete this cached item and its file?')) return;
    await explainerApi.cacheDelete(id);
    await load();
  };

  return (
    <div className="p-6 md:p-10 max-w-4xl mx-auto space-y-6">
      {/* Stats header */}
      <div className="glass-panel p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-white flex items-center gap-2">
            <Database size={16} className="text-cyan-400" />
            {stats ? `${stats.total_items} items · ${humanBytes(stats.total_bytes)}` : 'Content cache'}
          </h2>
          <button onClick={load} className="flex items-center gap-1.5 text-xs text-zinc-400 hover:text-white">
            <RotateCcw size={13} className={loading ? 'animate-spin' : ''} /> Refresh
          </button>
        </div>
        <div className="flex flex-wrap gap-2">
          {stats && Object.entries(stats.by_kind).sort((a, b) => b[1].bytes - a[1].bytes).map(([k, v]) => (
            <button
              key={k}
              onClick={() => setKind(kind === k ? '' : k)}
              className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${kind === k ? 'ring-1 ring-cyan-400 ' : ''}${KIND_TINT[k] || 'bg-white/5 text-zinc-300'}`}
            >
              {k} · {v.count} · {humanBytes(v.bytes)}{v.reuses ? ` · ${v.reuses}♻` : ''}
            </button>
          ))}
        </div>
      </div>

      {/* Filter */}
      <div className="flex items-center gap-3">
        <select value={kind} onChange={(e) => setKind(e.target.value)} className="input-field !py-2 !w-40">
          {KINDS.map((k) => <option key={k} value={k}>{k || 'all kinds'}</option>)}
        </select>
        <div className="flex-1 relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && load()}
            placeholder="Search source / labels…  (Enter)"
            className="input-field w-full !pl-9"
          />
        </div>
      </div>

      {/* Items */}
      <div className="space-y-1.5">
        {items.map((it) => (
          <div key={it.id} className="glass-panel p-3 flex items-center gap-3 text-sm">
            <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0 ${KIND_TINT[it.kind] || 'bg-white/5 text-zinc-300'}`}>{it.kind}</span>
            <div className="flex-1 min-w-0">
              <p className="text-zinc-200 truncate">{it.source || it.ref_key}</p>
              <p className="text-[11px] text-zinc-500 truncate">
                {humanBytes(it.bytes)}
                {it.size ? ` · ${it.size}` : ''}
                {it.duration_s ? ` · ${it.duration_s.toFixed(1)}s` : ''}
                {it.use_count > 1 ? ` · used ${it.use_count}×` : ''}
                {it.model ? ` · ${it.model}` : ''}
                {(it.labels || []).length ? ` · ${it.labels.slice(0, 4).join(', ')}` : ''}
              </p>
            </div>
            <button onClick={() => del(it.id)} className="shrink-0 p-1.5 rounded-lg text-zinc-500 hover:text-red-400 hover:bg-red-500/10 transition-colors" title="Delete">
              <Trash2 size={15} />
            </button>
          </div>
        ))}
        {items.length === 0 && <p className="text-zinc-600 text-sm text-center py-8">No cached items match.</p>}
      </div>
    </div>
  );
}
