import React, { useEffect, useRef } from 'react';
import { Loader2, CheckCircle2, AlertTriangle, X } from 'lucide-react';

// Live log for a running stage. The stages are slow and opaque (a download, an
// LLM call, whisper, a render poll) — showing the lines as they arrive is the
// difference between "working" and "hung".
export default function JobLog({ job, onClose }) {
  const endRef = useRef(null);
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'nearest' }); }, [job?.logs?.length]);
  if (!job) return null;

  const running = job.status === 'queued' || job.status === 'running';
  const Icon = running ? Loader2 : job.status === 'done' ? CheckCircle2 : AlertTriangle;
  const tint = running ? 'text-amber-400' : job.status === 'done' ? 'text-emerald-400' : 'text-red-400';

  return (
    <div className="glass-panel p-4 mb-5">
      <div className="flex items-center gap-2 mb-3">
        <Icon size={16} className={`${tint} ${running ? 'animate-spin' : ''}`} />
        <span className={`text-xs font-medium uppercase tracking-wider ${tint}`}>
          {job.stage || 'stage'} · {job.status}
        </span>
        {!running && onClose && (
          <button onClick={onClose} className="ml-auto text-zinc-500 hover:text-white transition-colors">
            <X size={14} />
          </button>
        )}
      </div>
      <pre className="text-[11px] leading-relaxed font-mono text-zinc-400 max-h-56 overflow-y-auto custom-scrollbar whitespace-pre-wrap">
        {(job.logs || []).join('\n') || 'starting…'}
        <span ref={endRef} />
      </pre>
      {job.error && <p className="text-xs text-red-300 mt-2">{job.error}</p>}
    </div>
  );
}
