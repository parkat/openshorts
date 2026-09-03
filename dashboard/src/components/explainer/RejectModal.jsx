import React, { useState } from 'react';
import { X, ThumbsDown, Loader2 } from 'lucide-react';
import { explainerApi, REJECT_TAGS } from './api';

// Reject a rendered project with a reason (+ category tags). The reason is fed
// into the NEXT script generation for this topic so the pipeline learns from it.
export default function RejectModal({ projectId, onClose, onDone }) {
  const [reason, setReason] = useState('');
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const toggle = (t) => setTags((cur) => cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]);

  const submit = async () => {
    if (!reason.trim()) { setErr('Add a reason so the next version can improve.'); return; }
    setBusy(true); setErr(null);
    try {
      await explainerApi.reject(projectId, reason.trim(), tags);
      onDone?.();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4" onClick={onClose}>
      <div className="glass-panel w-full max-w-lg p-5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-white font-semibold flex items-center gap-2"><ThumbsDown size={18} className="text-red-400" /> Reject this video</h3>
          <button onClick={onClose} className="text-zinc-500 hover:text-white"><X size={18} /></button>
        </div>

        <label className="text-xs text-zinc-400 uppercase tracking-wider">Why? (this teaches the next version)</label>
        <textarea
          autoFocus
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. The hook was too slow — it took 4 seconds to land the shocking fact. The middle dragged and the cat aid had garbled text."
          className="input-field w-full h-28 resize-none mt-1.5 mb-3"
        />

        <label className="text-xs text-zinc-400 uppercase tracking-wider">Category (optional)</label>
        <div className="flex flex-wrap gap-1.5 mt-1.5 mb-3">
          {REJECT_TAGS.map((t) => (
            <button
              key={t}
              onClick={() => toggle(t)}
              className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
                tags.includes(t) ? 'bg-red-500/20 text-red-300 ring-1 ring-red-400/50' : 'bg-white/5 text-zinc-400 hover:bg-white/10'
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        {err && <p className="text-xs text-red-300 mb-3">{err}</p>}

        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 rounded-lg text-sm text-zinc-400 hover:text-white transition-colors">Cancel</button>
          <button onClick={submit} disabled={busy} className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-red-500/15 text-red-300 hover:bg-red-500/25 transition-colors">
            {busy ? <Loader2 size={15} className="animate-spin" /> : <ThumbsDown size={15} />} Reject & save lesson
          </button>
        </div>
      </div>
    </div>
  );
}
