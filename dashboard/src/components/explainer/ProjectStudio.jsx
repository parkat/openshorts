import React, { useEffect, useState } from 'react';
import { ArrowLeft, RotateCcw, Copy, Check, AlertTriangle, Film, Pencil, Save, X, Loader2, ThumbsDown, MessageSquareWarning } from 'lucide-react';
import { explainerApi, STATUS_TINT, getApiUrl } from './api';
import StageBar from './StageBar';
import RejectModal from './RejectModal';

function CopyBtn({ text }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => {
        navigator.clipboard.writeText(text || '');
        setCopied(true);
        setTimeout(() => setCopied(false), 1200);
      }}
      className="flex items-center gap-1.5 text-xs text-zinc-400 hover:text-cyan-400 transition-colors shrink-0"
    >
      {copied ? <Check size={13} /> : <Copy size={13} />} {copied ? 'Copied' : 'Copy'}
    </button>
  );
}

function Flag({ f, onResolve }) {
  const block = f.level === 'block';
  const [busy, setBusy] = useState(false);
  return (
    <div className={`flex items-start gap-2 text-xs p-2.5 rounded-lg ${block ? 'bg-red-500/10 text-red-300' : 'bg-amber-500/10 text-amber-300'}`}>
      <span className="shrink-0">{block ? '⛔' : '⚠️'}</span>
      <div className="flex-1">
        <span className="font-mono opacity-70">{f.code}</span> — {f.message}
      </div>
      {onResolve && (
        <button
          onClick={async () => { setBusy(true); try { await onResolve(f); } finally { setBusy(false); } }}
          disabled={busy}
          className="shrink-0 px-2 py-0.5 rounded bg-white/10 hover:bg-white/20 text-white/80 transition-colors"
        >
          {busy ? '…' : 'Override'}
        </button>
      )}
    </div>
  );
}

// Read-only studio detail (Step 1). Stage buttons + editing land in later steps.
export default function ProjectStudio({ projectId, onBack }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [scriptText, setScriptText] = useState('');
  const [saveErr, setSaveErr] = useState(null);
  const [saving, setSaving] = useState(false);
  const [rejecting, setRejecting] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setDetail(await explainerApi.project(projectId));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); setEditing(false); }, [projectId]);

  const resolveFlag = async (f) => {
    await explainerApi.resolveFlag(projectId, 'clip', f);
    await load();
  };

  const startEdit = () => {
    setScriptText(JSON.stringify(detail?.draft?.script || {}, null, 2));
    setSaveErr(null);
    setEditing(true);
  };

  const saveScript = async () => {
    let parsed;
    try { parsed = JSON.parse(scriptText); } catch { setSaveErr('Invalid JSON'); return; }
    setSaving(true);
    setSaveErr(null);
    try {
      await explainerApi.saveScript(projectId, parsed);
      setEditing(false);
      await load();
    } catch (e) {
      setSaveErr(e.message);
    } finally {
      setSaving(false);
    }
  };

  const project = detail?.project;
  const script = detail?.draft?.script || {};
  const shots = script.shots || [];
  const flags = detail?.clip_flags || [];
  const factcheck = detail?.factcheck;
  const fcClaims = Array.isArray(factcheck) ? factcheck : (factcheck?.claims || []);
  const kit = detail?.post_kit;
  const feedback = detail?.feedback || [];

  return (
    <div className="p-6 md:p-10 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-5">
        <button onClick={onBack} className="flex items-center gap-2 text-sm text-zinc-400 hover:text-white transition-colors">
          <ArrowLeft size={16} /> Queue
        </button>
        <button onClick={load} className="flex items-center gap-2 text-xs text-zinc-400 hover:text-white transition-colors">
          <RotateCcw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {error && (
        <div className="glass-panel p-4 flex items-center gap-3 text-red-300 text-sm mb-4">
          <AlertTriangle size={16} /> {error}
        </div>
      )}

      {project && (
        <>
          <div className="flex items-start gap-3 mb-6">
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-mono text-zinc-600">#{project.id}</span>
                <span className={`text-[11px] px-2 py-0.5 rounded-md font-medium ${STATUS_TINT[project.status] || 'bg-zinc-500/15 text-zinc-300'}`}>
                  {project.status}
                </span>
                {detail?.draft?.status && (
                  <span className="text-[11px] px-2 py-0.5 rounded-md font-medium bg-white/5 text-zinc-400">
                    draft: {detail.draft.status}
                  </span>
                )}
              </div>
              <h1 className="text-2xl font-bold text-white">{project.title || '(untitled)'}</h1>
            </div>
            {detail.render_url && (
              <button
                onClick={() => setRejecting(true)}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium bg-red-500/10 text-red-300 hover:bg-red-500/20 transition-colors shrink-0"
                title="Reject this video with a reason — the next version learns from it"
              >
                <ThumbsDown size={15} /> Reject
              </button>
            )}
          </div>

          <div className="mb-6">
            <StageBar detail={detail} projectId={projectId} onChanged={load} />
          </div>

          <div className="grid md:grid-cols-2 gap-6">
            {/* Left: preview + flags */}
            <div className="space-y-6">
              <div className="glass-panel p-4">
                <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                  <Film size={14} /> Render
                </h3>
                {detail.render_url ? (
                  <video
                    src={getApiUrl(detail.render_url)}
                    controls
                    className="w-full rounded-lg bg-black aspect-[9/16] max-h-[70vh] mx-auto"
                  />
                ) : (
                  <div className="text-zinc-600 text-sm text-center py-10">No render yet.</div>
                )}
              </div>

              {flags.length > 0 && (
                <div className="glass-panel p-4 space-y-2">
                  <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">Guardrail flags (gate 1)</h3>
                  {flags.map((f, i) => <Flag key={i} f={f} onResolve={resolveFlag} />)}
                </div>
              )}

              {feedback.length > 0 && (
                <div className="glass-panel p-4 space-y-2">
                  <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2 flex items-center gap-2">
                    <MessageSquareWarning size={14} className="text-red-400" /> Rejection history — the next script learns from these
                  </h3>
                  {feedback.map((fb) => (
                    <div key={fb.id} className="text-xs p-2.5 rounded-lg bg-red-500/10 text-red-200">
                      <div className="flex items-center gap-2 mb-1">
                        {(fb.tags || []).map((t) => (
                          <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-300">{t}</span>
                        ))}
                        <span className="text-[10px] text-red-400/60 ml-auto">
                          {fb.project_id === projectId ? 'this project' : `project #${fb.project_id}`}
                          {fb.created_at ? ` · ${new Date(fb.created_at).toLocaleDateString()}` : ''}
                        </span>
                      </div>
                      {fb.reason}
                    </div>
                  ))}
                </div>
              )}

              {fcClaims.length > 0 && (
                <div className="glass-panel p-4 space-y-2">
                  <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">Fact-check</h3>
                  {fcClaims.map((c, i) => (
                    <div key={i} className={`text-xs p-2.5 rounded-lg ${c.label === 'supported' ? 'bg-emerald-500/10 text-emerald-300' : c.label === 'unsupported' ? 'bg-red-500/10 text-red-300' : 'bg-amber-500/10 text-amber-300'}`}>
                      <span className="font-mono opacity-70">[{c.label}]</span> {c.claim}
                      {c.note && <div className="opacity-70 mt-1">↳ {c.note}</div>}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Right: shot list + post kit */}
            <div className="space-y-6">
              <div className="glass-panel p-4">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
                    Shot list {shots.length ? `(${shots.length})` : ''}
                  </h3>
                  {!editing ? (
                    <button onClick={startEdit} className="flex items-center gap-1.5 text-xs text-zinc-400 hover:text-cyan-400 transition-colors">
                      <Pencil size={13} /> Edit
                    </button>
                  ) : (
                    <div className="flex items-center gap-2">
                      <button onClick={() => setEditing(false)} className="flex items-center gap-1 text-xs text-zinc-400 hover:text-white"><X size={13} /> Cancel</button>
                      <button onClick={saveScript} disabled={saving} className="flex items-center gap-1 text-xs text-cyan-300 hover:text-cyan-200">
                        {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />} Save
                      </button>
                    </div>
                  )}
                </div>

                {editing ? (
                  <>
                    {saveErr && <p className="text-xs text-red-300 mb-2 flex items-center gap-1.5"><AlertTriangle size={12} /> {saveErr}</p>}
                    <textarea
                      value={scriptText}
                      onChange={(e) => setScriptText(e.target.value)}
                      spellCheck={false}
                      className="input-field w-full h-[28rem] resize-none font-mono text-[11px] leading-relaxed"
                    />
                    <p className="text-[10px] text-zinc-600 mt-1">Editing the raw script JSON. Save writes it back to the draft; re-run Assets → Align → Render to apply.</p>
                  </>
                ) : (
                <>
                {script.hook && (
                  <p className="text-sm text-cyan-300 italic mb-3 leading-snug">“{script.hook}”</p>
                )}
                <div className="space-y-3">
                  {shots.map((sh, i) => (
                    <div key={i} className="text-sm border-l-2 border-white/10 pl-3">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className="text-[10px] font-mono uppercase text-zinc-500">{sh.role || '?'}</span>
                        <span className="text-[10px] text-zinc-600">{sh.seconds || '?'}s</span>
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/5 text-zinc-400">{sh.visual || '—'}</span>
                        {sh.speaks && <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-500/15 text-cyan-300">speaks</span>}
                      </div>
                      {sh.narration && <p className="text-zinc-200 leading-snug">{sh.narration}</p>}
                      {sh.visual_note && <p className="text-zinc-500 text-xs mt-1 leading-snug">{sh.visual_note}</p>}
                    </div>
                  ))}
                  {shots.length === 0 && <p className="text-zinc-600 text-sm">No script yet.</p>}
                </div>
                </>
                )}
              </div>

              {kit && (
                <div className="glass-panel p-4 space-y-4">
                  <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Post kit</h3>

                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[11px] text-zinc-500 uppercase tracking-wider">Title</span>
                      <CopyBtn text={kit.title} />
                    </div>
                    <p className="text-sm text-white bg-black/20 rounded-lg p-2.5">{kit.title}</p>
                  </div>

                  {['youtube', 'tiktok', 'instagram'].map((plat) => kit.captions?.[plat] && (
                    <div key={plat}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[11px] text-zinc-500 uppercase tracking-wider">{plat}</span>
                        <CopyBtn text={kit.captions[plat]} />
                      </div>
                      <p className="text-sm text-zinc-300 bg-black/20 rounded-lg p-2.5 leading-snug">{kit.captions[plat]}</p>
                    </div>
                  ))}

                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[11px] text-zinc-500 uppercase tracking-wider">Hashtags (10)</span>
                      <CopyBtn text={kit.hashtag_block} />
                    </div>
                    <p className="text-sm text-cyan-300 bg-black/20 rounded-lg p-2.5 font-mono leading-snug">{kit.hashtag_block}</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {rejecting && (
        <RejectModal
          projectId={projectId}
          onClose={() => setRejecting(false)}
          onDone={() => { setRejecting(false); load(); }}
        />
      )}
    </div>
  );
}
