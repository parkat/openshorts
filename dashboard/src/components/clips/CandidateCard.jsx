import React, { useState } from 'react';
import {
  Scissors, Clapperboard, Check, X, Trash2, ChevronDown, ChevronUp, Download, Repeat,
  Wand2, Send, Loader2,
} from 'lucide-react';
import { clipsApi, STATUS_TINT, fmtClock, getApiUrl } from './api';

// One proposed Short. Shows the model's case for the moment (score, why, the
// words actually spoken) so the call to cut it is made on evidence, and plays
// the render inline once there is one.
export default function CandidateCard({ candidate: c, mood, edit, busy, onRun, onChanged, onEdit }) {
  const [open, setOpen] = useState(false);
  const [queueing, setQueueing] = useState(false);
  const [queueError, setQueueError] = useState(null);
  const rendered = ['rendered', 'approved', 'rejected', 'scheduled'].includes(c.status);
  const isCut = c.status === 'cut' || rendered;

  const act = async (fn) => { await fn(); onChanged?.(); };

  // Queueing is synchronous and can fail for reasons you need to read (a dead
  // token, a paused calendar), so the error lands on the card rather than in a
  // job log you would have to go looking for.
  const queue = async () => {
    setQueueing(true);
    setQueueError(null);
    try {
      const res = await clipsApi.publish(c.id);
      const bad = (res.results || []).filter((r) => !r.ok);
      if (bad.length === (res.results || []).length) {
        throw new Error(bad[0]?.error || 'Buffer accepted nothing');
      }
      onChanged?.();
    } catch (e) {
      setQueueError(e.message);
    } finally {
      setQueueing(false);
    }
  };

  return (
    <div className="glass-panel p-4">
      <div className="flex items-start gap-3">
        <span className="text-xs font-mono text-zinc-600 shrink-0 pt-1">#{c.id}</span>
        <div className="flex-1 min-w-0">
          <p className="text-white font-medium leading-snug">{c.title || '(untitled)'}</p>
          {c.hook && <p className="text-xs text-cyan-300/80 mt-1 italic">“{c.hook}”</p>}
          <p className="text-[11px] text-zinc-500 mt-1.5 font-mono flex items-center gap-2">
            <span>{fmtClock(c.start_s)}–{fmtClock(c.end_s)} · {c.seconds}s</span>
            {c.payoff_s > 0 && (
              <span
                className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded ${
                  c.edit === 'loop' ? 'bg-cyan-500/15 text-cyan-300' : 'bg-white/5 text-zinc-500'
                }`}
                title={c.edit === 'loop'
                  ? `Cut as a loop: opens on the payoff at ${fmtClock(c.payoff_s)}`
                  : `Payoff starts at ${fmtClock(c.payoff_s)} — can be cut as a loop`}
              >
                <Repeat size={10} /> {fmtClock(c.payoff_s)}
              </span>
            )}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1.5 shrink-0">
          <span className={`text-[11px] px-2 py-1 rounded-md font-medium ${STATUS_TINT[c.status] || STATUS_TINT.candidate}`}>
            {c.status}
          </span>
          <span
            className="text-[11px] font-mono text-zinc-500"
            title="the model's confidence a stranger watches to the end"
          >
            {Number(c.score || 0).toFixed(2)}
          </span>
        </div>
      </div>

      {rendered && c.video_url && (
        <video
          src={getApiUrl(c.video_url)}
          controls
          preload="metadata"
          className="w-full max-w-[220px] rounded-lg mt-3 bg-black"
        />
      )}

      <div className="flex flex-wrap items-center gap-2 mt-3">
        <button
          onClick={() => onRun(() => clipsApi.cut(c.id, { edit }))}
          disabled={busy}
          title={isCut ? `re-cut as ${edit}` : `cut as ${edit}`}
          className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-300 disabled:opacity-40 transition-colors"
        >
          <Scissors size={13} /> {isCut ? 'Re-cut' : 'Cut'}
          {edit === 'loop' && <Repeat size={11} className="text-cyan-400" />}
        </button>
        {isCut && (
          <button
            onClick={() => onRun(() => clipsApi.render(c.id, { mood }))}
            disabled={busy}
            className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg bg-violet-500/10 hover:bg-violet-500/20 text-violet-300 disabled:opacity-40 transition-colors"
          >
            <Clapperboard size={13} /> {rendered ? 'Re-render' : 'Render'}
          </button>
        )}
        {rendered && (
          <button
            onClick={() => onEdit?.(c)}
            className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-300 transition-colors"
            title="subtitles, text overlay, publish copy"
          >
            <Wand2 size={13} /> Edit
          </button>
        )}
        {c.status === 'approved' && (
          <button
            onClick={queue}
            disabled={queueing}
            className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg bg-sky-500/10 hover:bg-sky-500/20 text-sky-300 disabled:opacity-40 transition-colors"
            title="queue into the shared publishing calendar"
          >
            {queueing ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />} Queue
          </button>
        )}
        {rendered && !['approved', 'scheduled'].includes(c.status) && (
          <button
            onClick={() => act(() => clipsApi.approve(c.id))}
            className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 transition-colors"
          >
            <Check size={13} /> Approve
          </button>
        )}
        {c.status !== 'rejected' && (
          <button
            onClick={() => act(() => clipsApi.reject(c.id))}
            className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg bg-white/5 hover:bg-red-500/15 text-zinc-400 hover:text-red-300 transition-colors"
          >
            <X size={13} /> Reject
          </button>
        )}
        {c.video_url && (
          <a
            href={getApiUrl(c.video_url)}
            download
            className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-300 transition-colors"
          >
            <Download size={13} /> MP4
          </a>
        )}
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-1 text-xs text-zinc-500 hover:text-white ml-auto transition-colors"
        >
          {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />} Why
        </button>
        <button
          onClick={() => act(() => clipsApi.deleteCandidate(c.id))}
          title="remove from the queue (files stay on disk)"
          className="text-zinc-600 hover:text-red-400 transition-colors"
        >
          <Trash2 size={13} />
        </button>
      </div>

      {queueError && (
        <p className="text-[11px] text-red-300 mt-2 leading-relaxed">{queueError}</p>
      )}

      {open && (
        <div className="mt-3 pt-3 border-t border-white/5 space-y-2">
          {c.reason && <p className="text-xs text-zinc-400 leading-relaxed">{c.reason}</p>}
          {c.quote && (
            <p className="text-[11px] text-zinc-500 leading-relaxed border-l-2 border-white/10 pl-3">
              {c.quote}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
