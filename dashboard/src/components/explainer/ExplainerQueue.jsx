import React, { useEffect, useState } from 'react';
import { RotateCcw, ChevronRight, AlertTriangle } from 'lucide-react';
import { explainerApi, STATUS_TINT } from './api';

// The project queue — every explainer project, newest-updated first. Click a row
// to open it in the studio.
export default function ExplainerQueue({ onOpen }) {
  const [projects, setProjects] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await explainerApi.queue();
      setProjects(data.projects || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="p-6 md:p-10 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider">
          Projects {projects ? `(${projects.length})` : ''}
        </h2>
        <button
          onClick={load}
          className="flex items-center gap-2 text-xs text-zinc-400 hover:text-white transition-colors"
        >
          <RotateCcw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {error && (
        <div className="glass-panel p-4 flex items-center gap-3 text-red-300 text-sm mb-4">
          <AlertTriangle size={16} /> {error}
        </div>
      )}

      {projects && projects.length === 0 && !error && (
        <div className="glass-panel p-8 text-center text-zinc-500 text-sm">
          No projects yet. Add a topic and generate a script to get started.
        </div>
      )}

      <div className="space-y-2">
        {(projects || []).map((p) => (
          <button
            key={p.id}
            onClick={() => onOpen(p.id)}
            className="glass-panel w-full flex items-center gap-4 p-4 text-left hover:bg-white/[0.06] transition-colors group"
          >
            <span className="text-xs font-mono text-zinc-600 w-10 shrink-0">#{p.id}</span>
            <div className="flex-1 min-w-0">
              <p className="text-white font-medium truncate">{p.title || '(untitled)'}</p>
              <p className="text-xs text-zinc-500 mt-0.5">
                topic {p.topic_id} · updated {p.updated_at ? new Date(p.updated_at).toLocaleString() : '—'}
              </p>
            </div>
            <span className={`text-[11px] px-2 py-1 rounded-md font-medium shrink-0 ${STATUS_TINT[p.status] || 'bg-zinc-500/15 text-zinc-300'}`}>
              {p.status}
            </span>
            {p.draft_status === 'approved' && (
              <span className="text-[11px] px-2 py-1 rounded-md font-medium bg-emerald-500/15 text-emerald-300 shrink-0">
                approved
              </span>
            )}
            <ChevronRight size={16} className="text-zinc-600 group-hover:text-cyan-400 transition-colors shrink-0" />
          </button>
        ))}
      </div>
    </div>
  );
}
