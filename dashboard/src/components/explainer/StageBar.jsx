import React, { useState } from 'react';
import { Play, Loader2, Terminal, ChevronDown, ChevronUp, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { explainerApi } from './api';
import useExplainerJob from './useExplainerJob';

// The stage-runner bar. Each button POSTs its stage route, gets a job_id, and
// streams live progress/logs via the poll hook. On finish, refreshes the studio.
// Step 2 wires Render; the remaining stages arrive in the next build step.
export default function StageBar({ detail, projectId, onChanged }) {
  const [showLogs, setShowLogs] = useState(false);
  const { job, start, running } = useExplainerJob((j) => {
    setShowLogs(true);
    onChanged?.(j);
  });

  const hasBlocks = (detail?.clip_flags || []).some((f) => f.level === 'block');
  const blockedResult = job?.status === 'done' && job?.result?.blocked;

  const runRender = (force) => {
    setShowLogs(true);
    start(() => explainerApi.render(projectId, { force }));
  };

  return (
    <div className="glass-panel p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Pipeline</h3>
        {job && (
          <button
            onClick={() => setShowLogs((v) => !v)}
            className="flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            <Terminal size={13} /> Logs {showLogs ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </button>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => runRender(false)}
          disabled={running}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            running ? 'bg-white/5 text-zinc-500 cursor-not-allowed'
                    : 'bg-cyan-500/15 text-cyan-300 hover:bg-cyan-500/25'
          }`}
        >
          {running ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
          {running ? 'Rendering…' : 'Render'}
        </button>

        {hasBlocks && (
          <span className="flex items-center gap-1.5 text-xs text-amber-300">
            <AlertTriangle size={13} /> block flags unresolved — use force
          </span>
        )}
      </div>

      {/* Live progress */}
      {running && (
        <div className="mt-3">
          <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
            <div
              className="h-full bg-cyan-400 transition-all duration-500"
              style={{ width: `${Math.round((job?.progress || 0) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Outcome */}
      {blockedResult && (
        <div className="mt-3 space-y-2">
          <div className="flex items-center gap-2 text-xs text-red-300">
            <AlertTriangle size={14} /> Render blocked by {job.result.blocks.length} guardrail flag(s).
          </div>
          <button
            onClick={() => runRender(true)}
            className="text-xs px-3 py-1.5 rounded-lg bg-red-500/15 text-red-300 hover:bg-red-500/25 transition-colors"
          >
            Force render anyway
          </button>
        </div>
      )}
      {job?.status === 'done' && !blockedResult && (
        <div className="mt-3 flex items-center gap-2 text-xs text-emerald-300">
          <CheckCircle2 size={14} /> Done.
        </div>
      )}
      {job?.status === 'error' && (
        <div className="mt-3 flex items-center gap-2 text-xs text-red-300">
          <AlertTriangle size={14} /> {job.error}
        </div>
      )}

      {/* Log stream */}
      {showLogs && job?.logs?.length > 0 && (
        <pre className="mt-3 max-h-48 overflow-y-auto custom-scrollbar bg-black/40 rounded-lg p-3 text-[11px] leading-relaxed text-zinc-400 font-mono whitespace-pre-wrap">
          {job.logs.join('\n')}
        </pre>
      )}
    </div>
  );
}
