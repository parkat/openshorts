import React, { useEffect, useState } from 'react';
import { RotateCcw, Calendar, Send, X, Trash2 } from 'lucide-react';
import { explainerApi } from './api';

export default function ScheduleView() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(null);
  const load = async () => { try { setData(await explainerApi.scheduleList()); } catch { /* ignore */ } };
  useEffect(() => { load(); }, []);

  const scheduled = data?.scheduled || [];
  const posts = data?.posts || [];
  const failedCount = scheduled.filter((s) => s.status === 'failed').length;

  const cancel = async (id) => {
    if (!window.confirm('Cancel this post? It will be removed from the Buffer queue.')) return;
    setBusy(id);
    try { await explainerApi.cancelScheduled(id); await load(); }
    catch (e) { window.alert(`Could not cancel: ${e.message}`); }
    finally { setBusy(null); }
  };

  const clearFailed = async () => {
    setBusy('failed');
    try { await explainerApi.clearFailedSchedule(); await load(); }
    finally { setBusy(null); }
  };

  return (
    <div className="p-6 md:p-10 max-w-3xl mx-auto space-y-8">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider flex items-center gap-2">
          <Calendar size={15} /> Scheduled ({scheduled.length})
        </h2>
        <div className="flex items-center gap-3">
          {failedCount > 0 && (
            <button onClick={clearFailed} disabled={busy === 'failed'} className="flex items-center gap-1.5 text-xs text-red-300 hover:text-red-200">
              <Trash2 size={13} /> Clear {failedCount} failed
            </button>
          )}
          <button onClick={load} className="flex items-center gap-1.5 text-xs text-zinc-400 hover:text-white"><RotateCcw size={13} /> Refresh</button>
        </div>
      </div>

      <div className="space-y-2">
        {scheduled.map((it) => (
          <div key={it.id} className="glass-panel p-3 flex items-center gap-3 text-sm">
            <span className="text-xs font-mono text-zinc-600 shrink-0">#{it.project_id}</span>
            <span className="px-2 py-0.5 rounded bg-white/5 text-zinc-300 text-xs">{it.platform}</span>
            <span className="flex-1 text-zinc-400 text-xs">{it.due_at ? new Date(it.due_at).toLocaleString() : '—'}</span>
            <span className={`text-xs px-2 py-0.5 rounded ${it.status === 'posted' ? 'bg-emerald-500/15 text-emerald-300' : it.status === 'failed' ? 'bg-red-500/15 text-red-300' : it.status === 'cancelled' ? 'bg-zinc-500/15 text-zinc-400' : 'bg-blue-500/15 text-blue-300'}`}>{it.status}</span>
            {it.status === 'queued' && (
              <button
                onClick={() => cancel(it.id)}
                disabled={busy === it.id}
                className="shrink-0 p-1 rounded text-zinc-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                title="Cancel this post (removes it from Buffer)"
              >
                <X size={14} />
              </button>
            )}
          </div>
        ))}
        {scheduled.length === 0 && <p className="text-zinc-600 text-sm">Nothing scheduled yet.</p>}
      </div>

      <div>
        <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider flex items-center gap-2 mb-3">
          <Send size={15} /> Publish log ({posts.length})
        </h2>
        <div className="space-y-2">
          {posts.map((p) => (
            <div key={p.id} className="glass-panel p-3 flex items-center gap-3 text-sm">
              <span className="text-xs font-mono text-zinc-600 shrink-0">#{p.project_id}</span>
              <span className="px-2 py-0.5 rounded bg-white/5 text-zinc-300 text-xs">{p.platform}</span>
              <span className="flex-1 text-zinc-400 text-xs truncate">{p.url || p.buffer_post_id || '—'}</span>
              <span className="text-xs text-zinc-500">{p.posted_at ? new Date(p.posted_at).toLocaleString() : ''}</span>
            </div>
          ))}
          {posts.length === 0 && <p className="text-zinc-600 text-sm">No posts logged yet.</p>}
        </div>
      </div>
    </div>
  );
}
