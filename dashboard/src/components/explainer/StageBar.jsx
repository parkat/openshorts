import React, { useState } from 'react';
import { Play, Loader2, Terminal, ChevronDown, ChevronUp, AlertTriangle, CheckCircle2, Settings2, Search, ShieldCheck, Layers, AlignLeft, Film, Send, ThumbsUp } from 'lucide-react';
import { explainerApi } from './api';
import useExplainerJob from './useExplainerJob';
import AssetsOptions from './AssetsOptions';

// Project-level pipeline stages, in order. (Script runs from the Topic view.)
const STAGES = [
  { key: 'clipfind', label: 'Clip-find', icon: Search },
  { key: 'factcheck', label: 'Fact-check', icon: ShieldCheck },
  { key: 'assets', label: 'Assets', icon: Layers, hasOpts: true },
  { key: 'align', label: 'Align', icon: AlignLeft },
  { key: 'render', label: 'Render', icon: Film },
];

export default function StageBar({ detail, projectId, onChanged }) {
  const [showLogs, setShowLogs] = useState(false);
  const [showAssetOpts, setShowAssetOpts] = useState(false);
  const [assetOpts, setAssetOpts] = useState({ speed: 1.0, aid_mode: 'motion' });
  const [busyAction, setBusyAction] = useState(null); // non-job actions (approve/schedule)
  const { job, start, running } = useExplainerJob((j) => { setShowLogs(true); onChanged?.(j); });

  const busy = running || !!busyAction;
  const hasBlocks = (detail?.clip_flags || []).some((f) => f.level === 'block');
  const blockedResult = job?.status === 'done' && job?.result?.blocked;
  const draftApproved = detail?.draft?.status === 'approved';

  const runStage = (key, extra = {}) => {
    setShowLogs(true);
    const args = key === 'assets' ? { ...assetOpts, ...extra } : extra;
    start(() => explainerApi[key](projectId, args));
  };

  const doAction = async (name, fn) => {
    setBusyAction(name);
    try { await fn(); onChanged?.(); } finally { setBusyAction(null); }
  };

  return (
    <div className="glass-panel p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Pipeline</h3>
        {job && (
          <button onClick={() => setShowLogs((v) => !v)} className="flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-300 transition-colors">
            <Terminal size={13} /> Logs {showLogs ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </button>
        )}
      </div>

      {/* Stage sequence */}
      <div className="flex flex-wrap items-center gap-2">
        {STAGES.map((st, i) => {
          const active = running && job?.stage === st.key;
          return (
            <React.Fragment key={st.key}>
              {i > 0 && <span className="text-zinc-700">→</span>}
              <div className="flex items-center">
                <button
                  onClick={() => runStage(st.key)}
                  disabled={busy}
                  className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                    active ? 'bg-cyan-500/25 text-cyan-200'
                           : busy ? 'bg-white/5 text-zinc-600 cursor-not-allowed'
                                  : 'bg-white/5 text-zinc-300 hover:bg-cyan-500/15 hover:text-cyan-300'
                  }`}
                >
                  {active ? <Loader2 size={14} className="animate-spin" /> : <st.icon size={14} />}
                  {st.label}
                </button>
                {st.hasOpts && (
                  <button
                    onClick={() => setShowAssetOpts((v) => !v)}
                    disabled={busy}
                    className="ml-1 p-1.5 rounded-lg text-zinc-500 hover:text-cyan-300 hover:bg-white/5 transition-colors"
                    title="Asset options"
                  >
                    <Settings2 size={14} />
                  </button>
                )}
              </div>
            </React.Fragment>
          );
        })}
      </div>

      {showAssetOpts && <AssetsOptions opts={assetOpts} setOpts={setAssetOpts} />}

      {hasBlocks && (
        <div className="mt-3 flex items-center gap-1.5 text-xs text-amber-300">
          <AlertTriangle size={13} /> Guardrail block flags unresolved — Render will need force.
        </div>
      )}

      {/* Gate 2 + publish */}
      <div className="mt-3 pt-3 border-t border-white/5 flex flex-wrap items-center gap-2">
        <button
          onClick={() => doAction('approve', () => explainerApi.approve(projectId))}
          disabled={busy || draftApproved}
          className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
            draftApproved ? 'bg-emerald-500/15 text-emerald-300'
                          : busy ? 'bg-white/5 text-zinc-600 cursor-not-allowed'
                                 : 'bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20'
          }`}
        >
          {busyAction === 'approve' ? <Loader2 size={14} className="animate-spin" /> : <ThumbsUp size={14} />}
          {draftApproved ? 'Approved' : 'Approve (gate 2)'}
        </button>
        <button
          onClick={() => doAction('schedule', () => explainerApi.schedule(projectId))}
          disabled={busy || !draftApproved}
          className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
            busy || !draftApproved ? 'bg-white/5 text-zinc-600 cursor-not-allowed'
                                   : 'bg-blue-500/10 text-blue-300 hover:bg-blue-500/20'
          }`}
          title={draftApproved ? 'Schedule to Buffer' : 'Approve first'}
        >
          {busyAction === 'schedule' ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
          Schedule
        </button>
      </div>

      {/* Live progress */}
      {running && (
        <div className="mt-3">
          <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
            <div className="h-full bg-cyan-400 transition-all duration-500" style={{ width: `${Math.round((job?.progress || 0) * 100)}%` }} />
          </div>
        </div>
      )}

      {/* Outcomes */}
      {blockedResult && (
        <div className="mt-3 space-y-2">
          <div className="flex items-center gap-2 text-xs text-red-300">
            <AlertTriangle size={14} /> Render blocked by {job.result.blocks.length} guardrail flag(s).
          </div>
          <button onClick={() => runStage('render', { force: true })} className="text-xs px-3 py-1.5 rounded-lg bg-red-500/15 text-red-300 hover:bg-red-500/25 transition-colors">
            Force render anyway
          </button>
        </div>
      )}
      {job?.status === 'done' && !blockedResult && (
        <div className="mt-3 flex items-center gap-2 text-xs text-emerald-300"><CheckCircle2 size={14} /> {job.stage} done.</div>
      )}
      {job?.status === 'error' && (
        <div className="mt-3 flex items-center gap-2 text-xs text-red-300"><AlertTriangle size={14} /> {job.error}</div>
      )}

      {showLogs && job?.logs?.length > 0 && (
        <pre className="mt-3 max-h-48 overflow-y-auto custom-scrollbar bg-black/40 rounded-lg p-3 text-[11px] leading-relaxed text-zinc-400 font-mono whitespace-pre-wrap">
          {job.logs.join('\n')}
        </pre>
      )}
    </div>
  );
}
