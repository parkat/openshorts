import React, { useCallback, useEffect, useState } from 'react';
import {
  Send, RotateCcw, AlertTriangle, CheckCircle2, Pause, Play, X, Trash2, Plus,
  Calendar, Clock, Loader2, Radio,
} from 'lucide-react';
import {
  publishingApi, PLATFORM_LABEL, LANE_LABEL, LANE_TINT, STATUS_TINT,
  COMMON_TIMEZONES, fmtWhen,
} from './api';

// Publishing — one calendar for every lane.
//
// The page is ordered by what goes wrong most often. Buffer's token expires
// silently and every downstream failure then looks like something else, so the
// connection is the first thing on screen and says so in words. Below it the
// behaviour that governs the queue, then the queue itself.
export default function PublishingTab() {
  const [data, setData] = useState(null);
  const [queue, setQueue] = useState({ scheduled: [], posts: [] });
  const [ready, setReady] = useState({});
  const [draft, setDraft] = useState(null);      // unsaved settings edits
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const load = useCallback(async () => {
    setBusy('load');
    try {
      const [st, q, r] = await Promise.all([
        publishingApi.status(), publishingApi.queue(), publishingApi.ready(),
      ]);
      setData(st);
      setDraft(st.settings);
      setQueue(q);
      setReady(r);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const run = async (label, fn, msg) => {
    setBusy(label);
    setError(null);
    setNotice(null);
    try {
      await fn();
      if (msg) setNotice(msg);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  if (!data || !draft) {
    return (
      <div className="h-full flex items-center justify-center text-zinc-500 text-sm gap-2">
        <Loader2 size={16} className="animate-spin" /> Loading the calendar…
      </div>
    );
  }

  const conn = data.connection || {};
  const dirty = JSON.stringify(draft) !== JSON.stringify(data.settings);
  const set = (patch) => setDraft({ ...draft, ...patch });
  const setLane = (lane, patch) => set({
    lanes: { ...draft.lanes, [lane]: { ...draft.lanes[lane], ...patch } },
  });

  const scheduled = queue.scheduled.filter((r) => r.status === 'queued');
  const failed = queue.scheduled.filter((r) => r.status === 'failed');
  const readyCount = (ready.clips?.length || 0) + (ready.explainer?.length || 0);

  return (
    <div className="h-full flex flex-col animate-[fadeIn_0.3s_ease-out]">
      <div className="px-6 md:px-10 pt-6 pb-4 border-b border-white/5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-sky-500/10 text-sky-400 flex items-center justify-center">
            <Send size={19} />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white leading-none">Publishing</h1>
            <p className="text-xs text-zinc-500 mt-1">
              One Buffer calendar for every lane — what goes out, where, and when.
            </p>
          </div>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-2 text-xs text-zinc-400 hover:text-white transition-colors"
        >
          <RotateCcw size={14} className={busy === 'load' ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      <div className="flex-1 overflow-y-auto custom-scrollbar p-6 md:p-10">
        <div className="max-w-4xl mx-auto space-y-6">

          {error && (
            <div className="glass-panel p-4 flex items-start gap-3 text-red-300 text-sm">
              <AlertTriangle size={16} className="shrink-0 mt-0.5" /> {error}
            </div>
          )}
          {notice && (
            <div className="glass-panel p-4 flex items-start gap-3 text-emerald-300 text-sm">
              <CheckCircle2 size={16} className="shrink-0 mt-0.5" /> {notice}
            </div>
          )}

          {/* --- Connection ------------------------------------------------ */}
          <div className="glass-panel p-5">
            <div className="flex items-start gap-3">
              <div className={`w-2.5 h-2.5 rounded-full mt-1.5 shrink-0 ${
                conn.ok ? 'bg-emerald-400' : 'bg-red-400'
              }`}
              />
              <div className="flex-1 min-w-0">
                <h2 className="text-sm font-semibold text-white">
                  {conn.ok ? 'Buffer connected' : 'Buffer not connected'}
                </h2>
                {conn.ok ? (
                  <div className="flex flex-wrap gap-2 mt-3">
                    {(conn.channels || []).map((c) => (
                      <span
                        key={c.id}
                        className="px-2.5 py-1 rounded-lg bg-white/5 text-xs text-zinc-300"
                      >
                        {PLATFORM_LABEL[c.service] || c.service}
                        <span className="text-zinc-500"> · {c.name}</span>
                      </span>
                    ))}
                    {!(conn.channels || []).length && (
                      <span className="text-xs text-zinc-500">
                        The token works but the account has no channels.
                      </span>
                    )}
                  </div>
                ) : (
                  <>
                    <p className="text-xs text-red-300/90 mt-1.5 leading-relaxed">
                      {conn.error}
                    </p>
                    <p className="text-[11px] text-zinc-500 mt-2 leading-relaxed">
                      Nothing can be queued until this is fixed. The key is
                      server-side: set <span className="font-mono">BUFFER</span> in
                      the box&apos;s <span className="font-mono">.env</span> from a
                      personal token at publish.buffer.com/settings/api, then restart
                      the backend.
                    </p>
                  </>
                )}
              </div>
              <button
                onClick={() => run('conn', () => publishingApi.connection())}
                disabled={busy === 'conn'}
                className="text-xs text-zinc-400 hover:text-white shrink-0 transition-colors"
              >
                {busy === 'conn' ? 'Testing…' : 'Test'}
              </button>
            </div>
          </div>

          {/* --- Behaviour -------------------------------------------------- */}
          <div className="glass-panel p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-zinc-300">Posting behaviour</h2>
              <button
                onClick={() => run('reset', () => publishingApi.resetSettings(),
                  'Back to the brand defaults.')}
                className="text-[11px] text-zinc-500 hover:text-white transition-colors"
                title="discard every override and use brand.py"
              >
                Reset to defaults
              </button>
            </div>

            {/* Pause */}
            <button
              onClick={() => set({ paused: !draft.paused })}
              className={`w-full flex items-center gap-3 p-3 rounded-xl border transition-colors mb-5 ${
                draft.paused
                  ? 'bg-amber-500/10 border-amber-500/30 text-amber-200'
                  : 'bg-white/[0.03] border-white/5 text-zinc-300 hover:bg-white/[0.06]'
              }`}
            >
              {draft.paused ? <Pause size={16} /> : <Play size={16} />}
              <span className="text-sm font-medium">
                {draft.paused ? 'Publishing is paused' : 'Publishing is live'}
              </span>
              <span className="text-[11px] text-zinc-500 ml-auto text-left">
                {draft.paused
                  ? 'Nothing is queued, by hand or automatically. Already-queued posts still go out.'
                  : 'Click to hold everything without stopping anything else on the box.'}
              </span>
            </button>

            {/* Slots */}
            <div className="grid md:grid-cols-2 gap-5">
              <div>
                <label className="block text-xs text-zinc-500 mb-2">
                  Daily slots ({draft.publish_times.length})
                </label>
                <div className="space-y-2">
                  {draft.publish_times.map((t, i) => (
                    <div key={`${t}-${i}`} className="flex items-center gap-2">
                      <Clock size={13} className="text-zinc-600 shrink-0" />
                      <input
                        type="time"
                        value={t}
                        onChange={(e) => {
                          const next = [...draft.publish_times];
                          next[i] = e.target.value;
                          set({ publish_times: next });
                        }}
                        className="input-field py-1.5 text-sm w-32"
                      />
                      {draft.publish_times.length > 1 && (
                        <button
                          onClick={() => set({
                            publish_times: draft.publish_times.filter((_, j) => j !== i),
                          })}
                          className="text-zinc-600 hover:text-red-400 transition-colors"
                        >
                          <X size={14} />
                        </button>
                      )}
                    </div>
                  ))}
                </div>
                <button
                  onClick={() => set({ publish_times: [...draft.publish_times, '12:00'] })}
                  className="flex items-center gap-1.5 text-[11px] text-zinc-500 hover:text-white mt-2 transition-colors"
                >
                  <Plus size={12} /> Add a slot
                </button>
                <p className="text-[11px] text-zinc-600 mt-3 leading-relaxed">
                  Wall-clock times, so they track daylight saving on their own. A slot
                  holds one post — the lanes share them, which is what stops two
                  videos landing on the same minute.
                </p>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="block text-xs text-zinc-500 mb-1.5">Timezone</label>
                  <select
                    value={draft.timezone}
                    onChange={(e) => set({ timezone: e.target.value })}
                    className="input-field py-2 text-sm"
                  >
                    {[...new Set([draft.timezone, ...COMMON_TIMEZONES])].map((z) => (
                      <option key={z} value={z}>{z}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs text-zinc-500 mb-1.5">Platforms</label>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(PLATFORM_LABEL).map(([id, label]) => {
                      const on = draft.platforms.includes(id);
                      return (
                        <button
                          key={id}
                          onClick={() => set({
                            platforms: on
                              ? draft.platforms.filter((p) => p !== id)
                              : [...draft.platforms, id],
                          })}
                          className={`px-3 py-1.5 rounded-lg text-xs transition-colors ${
                            on ? 'bg-sky-500/15 text-sky-300' : 'bg-white/5 text-zinc-500 hover:text-zinc-300'
                          }`}
                        >
                          {label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div>
                  <label className="block text-xs text-zinc-500 mb-1.5">
                    When the slot arrives
                  </label>
                  <select
                    value={draft.scheduling}
                    onChange={(e) => set({ scheduling: e.target.value })}
                    className="input-field py-2 text-sm"
                  >
                    <option value="automatic">Buffer publishes it</option>
                    <option value="notification">Buffer reminds me to</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Lanes */}
            <div className="mt-6 pt-5 border-t border-white/5">
              <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3">
                Per lane
              </h3>
              <div className="space-y-2">
                {Object.keys(LANE_LABEL).map((lane) => {
                  const cfg = draft.lanes[lane] || {};
                  return (
                    <div key={lane} className="flex flex-wrap items-center gap-3 p-3 rounded-xl bg-white/[0.03]">
                      <span className={`px-2 py-0.5 rounded text-xs shrink-0 ${LANE_TINT[lane]}`}>
                        {LANE_LABEL[lane]}
                      </span>
                      <button
                        onClick={() => setLane(lane, { enabled: !cfg.enabled })}
                        className={`text-xs px-2.5 py-1 rounded-lg transition-colors ${
                          cfg.enabled ? 'bg-emerald-500/10 text-emerald-300' : 'bg-white/5 text-zinc-500'
                        }`}
                      >
                        {cfg.enabled ? 'can publish' : 'off'}
                      </button>
                      <button
                        onClick={() => setLane(lane, { auto: !cfg.auto })}
                        disabled={!cfg.enabled}
                        className={`text-xs px-2.5 py-1 rounded-lg transition-colors disabled:opacity-30 ${
                          cfg.auto ? 'bg-sky-500/10 text-sky-300' : 'bg-white/5 text-zinc-500'
                        }`}
                        title={cfg.auto
                          ? 'the worker queues approved items on its own'
                          : 'you queue each item by hand'}
                      >
                        {cfg.auto ? 'auto-drip' : 'hand-queued'}
                      </button>
                      <label className="flex items-center gap-2 text-xs text-zinc-500 ml-auto">
                        max/day
                        <input
                          type="number"
                          min={0}
                          max={draft.publish_times.length}
                          value={cfg.per_day ?? 1}
                          onChange={(e) => setLane(lane, { per_day: Number(e.target.value) })}
                          className="input-field py-1 text-sm w-16"
                        />
                      </label>
                    </div>
                  );
                })}
              </div>
              <p className="text-[11px] text-zinc-600 mt-3 leading-relaxed">
                <strong>Auto-drip</strong> lets the background worker queue approved
                work without you. Clips ships hand-queued: a batch of ten from one
                source is meant to be released deliberately, not emptied into the
                calendar the moment it renders.
              </p>
            </div>

            {dirty && (
              <div className="flex items-center gap-3 mt-5 pt-4 border-t border-white/5">
                <button
                  onClick={() => run('save', () => publishingApi.saveSettings(draft),
                    'Saved.')}
                  disabled={busy === 'save'}
                  className="btn-primary flex items-center gap-2 text-sm px-4 py-2 disabled:opacity-40"
                >
                  {busy === 'save' ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                  Save changes
                </button>
                <button
                  onClick={() => setDraft(data.settings)}
                  className="text-xs text-zinc-500 hover:text-white transition-colors"
                >
                  Discard
                </button>
              </div>
            )}
          </div>

          {/* --- Ready to go ------------------------------------------------ */}
          {readyCount > 0 && (
            <div className="glass-panel p-5">
              <h2 className="text-sm font-semibold text-zinc-300 mb-1">
                Ready to queue ({readyCount})
              </h2>
              <p className="text-[11px] text-zinc-600 mb-4 leading-relaxed">
                Approved and rendered, holding no slot yet. The next free one is{' '}
                {fmtWhen(data.next_slot?.clips || data.next_slot?.explainer)}.
              </p>
              <div className="space-y-2">
                {Object.keys(LANE_LABEL).flatMap((lane) => (ready[lane] || []).map((r) => (
                  <div key={`${lane}-${r.ref_id}`} className="flex items-center gap-3 p-3 rounded-xl bg-white/[0.03]">
                    <span className={`px-2 py-0.5 rounded text-[11px] shrink-0 ${LANE_TINT[lane]}`}>
                      {LANE_LABEL[lane]}
                    </span>
                    <span className="text-xs font-mono text-zinc-600 shrink-0">#{r.ref_id}</span>
                    <span className="flex-1 min-w-0 truncate text-sm text-zinc-300">
                      {r.title || '(untitled)'}
                    </span>
                    <button
                      onClick={() => run(`pub-${lane}-${r.ref_id}`,
                        () => publishingApi.publish(lane, r.ref_id),
                        `Queued ${LANE_LABEL[lane]} #${r.ref_id}.`)}
                      disabled={!!busy || !conn.ok || draft.paused}
                      className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg bg-sky-500/10 hover:bg-sky-500/20 text-sky-300 disabled:opacity-30 shrink-0 transition-colors"
                      title={conn.ok ? 'queue into the next free slot' : 'Buffer is not connected'}
                    >
                      {busy === `pub-${lane}-${r.ref_id}`
                        ? <Loader2 size={12} className="animate-spin" />
                        : <Send size={12} />}
                      Queue
                    </button>
                  </div>
                )))}
              </div>
            </div>
          )}

          {/* --- The calendar ----------------------------------------------- */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider flex items-center gap-2">
                <Calendar size={15} /> Scheduled ({scheduled.length})
              </h2>
              {failed.length > 0 && (
                <button
                  onClick={() => run('clear', () => publishingApi.clearFailed(),
                    `Cleared ${failed.length} failed row(s).`)}
                  className="flex items-center gap-1.5 text-xs text-red-300 hover:text-red-200 transition-colors"
                >
                  <Trash2 size={13} /> Clear {failed.length} failed
                </button>
              )}
            </div>

            {queue.scheduled.length === 0 ? (
              <div className="glass-panel p-8 text-center text-zinc-500 text-sm">
                Nothing scheduled. Approve something in a lane, then queue it here.
              </div>
            ) : (
              <div className="space-y-2">
                {queue.scheduled.map((it) => (
                  <div key={it.id} className="glass-panel flex items-center gap-3 p-3">
                    <span className={`px-2 py-0.5 rounded text-[11px] shrink-0 ${LANE_TINT[it.lane] || ''}`}>
                      {LANE_LABEL[it.lane] || it.lane}
                    </span>
                    <span className="text-xs font-mono text-zinc-600 shrink-0">#{it.ref_id}</span>
                    <span className="flex-1 min-w-0">
                      <span className="block text-sm text-zinc-300 truncate">
                        {it.title || '(untitled)'}
                      </span>
                      <span className="block text-[11px] text-zinc-600">
                        {PLATFORM_LABEL[it.platform] || it.platform} · {fmtWhen(it.due_at)}
                      </span>
                    </span>
                    <span className={`text-[11px] px-2 py-0.5 rounded shrink-0 ${STATUS_TINT[it.status] || ''}`}>
                      {it.status}
                    </span>
                    {it.status === 'queued' && (
                      <button
                        onClick={() => run(`cancel-${it.id}`, () => publishingApi.cancel(it.id),
                          'Pulled back out of Buffer.')}
                        disabled={!!busy}
                        className="shrink-0 p-1 rounded text-zinc-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                        title="cancel — removes it from Buffer too"
                      >
                        {busy === `cancel-${it.id}`
                          ? <Loader2 size={14} className="animate-spin" />
                          : <X size={14} />}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* --- Publish log ------------------------------------------------ */}
          <div>
            <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider flex items-center gap-2 mb-3">
              <Radio size={15} /> Publish log ({queue.posts.length})
            </h2>
            {queue.posts.length === 0 ? (
              <p className="text-zinc-600 text-sm">Nothing has gone out yet.</p>
            ) : (
              <div className="space-y-2">
                {queue.posts.map((p) => (
                  <div key={p.id} className="glass-panel flex items-center gap-3 p-3 text-sm">
                    <span className={`px-2 py-0.5 rounded text-[11px] shrink-0 ${LANE_TINT[p.lane] || ''}`}>
                      {LANE_LABEL[p.lane] || p.lane}
                    </span>
                    <span className="text-xs font-mono text-zinc-600 shrink-0">#{p.ref_id}</span>
                    <span className="flex-1 min-w-0 truncate text-zinc-400 text-xs">
                      {p.title || p.url || p.buffer_post_id || '—'}
                    </span>
                    <span className="text-[11px] text-zinc-600 shrink-0">
                      {PLATFORM_LABEL[p.platform] || p.platform}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
