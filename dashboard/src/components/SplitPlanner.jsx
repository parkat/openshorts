import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
    ArrowLeft, Scissors, RefreshCw, Trash2, RotateCcw, Play, Type, Captions, Film,
} from 'lucide-react';
import { getApiUrl } from '../config';

/**
 * Preview and edit a split-into-parts plan before anything renders.
 *
 * Forty parts is forty renders, and on a two-hour source that is hours of GPU time —
 * far too late to discover that the boundaries are wrong or that every part is
 * called "Part 1". So the cut list is computed up front (it's arithmetic on the
 * duration, not an LLM call), shown with a poster frame each, and only handed to
 * the renderer once it's approved.
 *
 * Naming lives server-side: this sends edits to /api/split/plan/{id}/apply and
 * renders whatever comes back, so the preview and the render fill the same
 * placeholders from the same code.
 */

const SUB_POSITIONS = [
    { v: 'bottom', l: 'Bottom' },
    { v: 'middle', l: 'Middle' },
    { v: 'top', l: 'Top' },
];

const DEFAULT_SUBTITLE_STYLE = {
    position: 'bottom',
    font_size: 16,
    font_name: 'Verdana',
    font_color: '#FFFFFF',
    border_color: '#000000',
    border_width: 2,
    bg_color: '#000000',
    bg_opacity: 0,
    margin_v: 25,
    hook_position: 'top',
    hook_scale: 1.0,
};

const timecode = (seconds) => {
    const total = Math.max(0, Math.round(seconds || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    const mm = String(m).padStart(2, '0');
    const ss = String(s).padStart(2, '0');
    return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
};

export default function SplitPlanner({ plan: initialPlan, layout: initialLayout, onBack, onRender }) {
    const [plan, setPlan] = useState(initialPlan);
    const [layout, setLayout] = useState(initialLayout || 'auto');
    const [partLength, setPartLength] = useState(initialPlan.part_length);
    const [titleTemplate, setTitleTemplate] = useState(initialPlan.title_template || '');
    const [hookTemplate, setHookTemplate] = useState(initialPlan.hook_template || '');
    const [descriptionTemplate, setDescriptionTemplate] = useState(initialPlan.description_template || '');
    const [bakeHooks, setBakeHooks] = useState(false);
    const [bakeSubtitles, setBakeSubtitles] = useState(false);
    const [subtitleStyle, setSubtitleStyle] = useState(DEFAULT_SUBTITLE_STYLE);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');

    const parts = plan.parts || [];
    const thumbsPending = plan.thumbs && plan.thumbs.state !== 'done';
    const pendingApply = useRef(null);

    const applyPlan = useCallback(async (payload) => {
        setBusy(true);
        setError('');
        try {
            const res = await fetch(getApiUrl(`/api/split/plan/${plan.plan_id}/apply`), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (!res.ok) throw new Error(await res.text());
            setPlan(await res.json());
        } catch (e) {
            setError(e.message || 'Could not update the plan.');
        } finally {
            setBusy(false);
        }
    }, [plan.plan_id]);

    // Poster frames arrive after the plan does — poll until the last one lands,
    // merging only the thumbnails so an in-flight edit isn't clobbered.
    useEffect(() => {
        if (!thumbsPending) return undefined;
        const timer = setInterval(async () => {
            try {
                const res = await fetch(getApiUrl(`/api/split/plan/${plan.plan_id}`));
                if (!res.ok) return;
                const fresh = await res.json();
                setPlan((prev) => {
                    const urls = new Map((fresh.parts || []).map((p) => [p.index, p.thumb_url]));
                    return {
                        ...prev,
                        thumbs: fresh.thumbs,
                        parts: (prev.parts || []).map((p) => (
                            urls.get(p.index) ? { ...p, thumb_url: urls.get(p.index) } : p
                        )),
                    };
                });
            } catch {
                /* transient — the next tick retries */
            }
        }, 1500);
        return () => clearInterval(timer);
    }, [thumbsPending, plan.plan_id]);

    const editPart = (index, changes) => {
        setPlan((prev) => ({
            ...prev,
            parts: prev.parts.map((p) => (p.index === index ? { ...p, ...changes } : p)),
        }));
    };

    // Boundary edits go through the server (renumber + re-template + fresh frame),
    // debounced so dragging a value around isn't forty round trips.
    const queueBoundaryApply = (nextParts) => {
        clearTimeout(pendingApply.current);
        pendingApply.current = setTimeout(() => applyPlan({ parts: nextParts }), 700);
    };

    const nudge = (part, field, delta) => {
        const limit = plan.duration;
        const value = Math.max(0, Math.min(limit, (part[field] || 0) + delta));
        const changes = { [field]: Number(value.toFixed(3)) };
        editPart(part.index, changes);
        queueBoundaryApply(plan.parts.map((p) => (p.index === part.index ? { ...p, ...changes } : p)));
    };

    const removePart = (index) => {
        const next = plan.parts.filter((p) => p.index !== index);
        if (!next.length) return;
        setPlan((prev) => ({ ...prev, parts: next }));
        applyPlan({ parts: next });
    };

    const resetOverrides = (index) => {
        const changes = { title_locked: false, hook_locked: false, description_locked: false };
        const next = plan.parts.map((p) => (p.index === index ? { ...p, ...changes } : p));
        setPlan((prev) => ({ ...prev, parts: next }));
        applyPlan({ parts: next });
    };

    const applyNaming = () => applyPlan({
        parts: plan.parts,
        title_template: titleTemplate,
        hook_template: hookTemplate,
        description_template: descriptionTemplate,
    });

    const resplit = () => applyPlan({
        part_length: Number(partLength) || plan.part_length,
        resplit: true,
        title_template: titleTemplate,
        hook_template: hookTemplate,
        description_template: descriptionTemplate,
    });

    const submit = () => {
        onRender({
            plan_id: plan.plan_id,
            local_path: plan.source_path,
            parts: plan.parts,
            layout,
            bake_hooks: bakeHooks,
            subtitles: bakeSubtitles ? subtitleStyle : null,
        });
    };

    const totalRuntime = parts.reduce((sum, p) => sum + Math.max(0, (p.end || 0) - (p.start || 0)), 0);

    return (
        <div className="animate-[fadeIn_0.4s_ease-out] space-y-5">
            <div className="flex items-start justify-between gap-4">
                <div>
                    <button onClick={onBack} className="flex items-center gap-2 text-sm text-zinc-400 hover:text-white mb-2">
                        <ArrowLeft size={16} />
                        Pick a different source
                    </button>
                    <h2 className="text-2xl font-bold text-white flex items-center gap-2">
                        <Scissors size={22} className="text-primary" />
                        {parts.length} parts
                    </h2>
                    <p className="text-sm text-zinc-500 mt-1">
                        {plan.source_name} · {timecode(plan.duration)} source · {timecode(totalRuntime)} across all parts
                        {thumbsPending && plan.thumbs && (
                            <span className="text-zinc-400"> · frames {plan.thumbs.done}/{plan.thumbs.total}</span>
                        )}
                    </p>
                </div>
                <button
                    onClick={submit}
                    disabled={busy || !parts.length}
                    className="btn-primary flex items-center gap-2 shrink-0"
                >
                    <Play size={18} />
                    Render {parts.length} parts
                </button>
            </div>

            {error && (
                <div className="bg-red-500/10 border border-red-500/30 text-red-300 text-sm rounded-xl px-4 py-3">
                    {error}
                </div>
            )}

            <div className="bg-surface border border-white/5 rounded-2xl p-5 space-y-5">
                <div className="flex flex-wrap items-end gap-3">
                    <div>
                        <p className="text-xs text-zinc-500 mb-1">Part length (seconds)</p>
                        <input
                            type="number"
                            min={10}
                            max={3600}
                            value={partLength}
                            onChange={(e) => setPartLength(e.target.value)}
                            className="input-field w-32"
                        />
                    </div>
                    <button
                        type="button"
                        onClick={resplit}
                        disabled={busy}
                        className="flex items-center gap-2 px-4 py-2 rounded-lg border border-white/10 bg-white/5 text-sm text-zinc-300 hover:text-white"
                    >
                        <RefreshCw size={15} className={busy ? 'animate-spin' : ''} />
                        Re-split
                    </button>
                    <p className="text-xs text-zinc-600 pb-2">Re-splitting discards any boundary edits.</p>
                </div>

                <div className="grid md:grid-cols-3 gap-3">
                    <div>
                        <p className="text-xs text-zinc-500 mb-1 flex items-center gap-1"><Type size={13} /> Title template</p>
                        <input
                            type="text"
                            value={titleTemplate}
                            onChange={(e) => setTitleTemplate(e.target.value)}
                            onBlur={applyNaming}
                            className="input-field"
                            spellCheck={false}
                        />
                    </div>
                    <div>
                        <p className="text-xs text-zinc-500 mb-1">Hook template</p>
                        <input
                            type="text"
                            value={hookTemplate}
                            onChange={(e) => setHookTemplate(e.target.value)}
                            onBlur={applyNaming}
                            className="input-field"
                            spellCheck={false}
                        />
                    </div>
                    <div>
                        <p className="text-xs text-zinc-500 mb-1">Description template</p>
                        <input
                            type="text"
                            value={descriptionTemplate}
                            onChange={(e) => setDescriptionTemplate(e.target.value)}
                            onBlur={applyNaming}
                            className="input-field"
                            placeholder="(optional)"
                            spellCheck={false}
                        />
                    </div>
                </div>
                <p className="text-xs text-zinc-600">
                    Placeholders: <code className="text-zinc-400">{'{n}'}</code> part number,
                    {' '}<code className="text-zinc-400">{'{nn}'}</code> zero-padded,
                    {' '}<code className="text-zinc-400">{'{total}'}</code> part count,
                    {' '}<code className="text-zinc-400">{'{name}'}</code> source name,
                    {' '}<code className="text-zinc-400">{'{start}'}</code>/<code className="text-zinc-400">{'{end}'}</code>/<code className="text-zinc-400">{'{duration}'}</code> timecodes.
                    Hand-typed text is kept when the templates change.
                </p>

                <div className="grid md:grid-cols-2 gap-4 pt-1">
                    <div>
                        <p className="text-xs text-zinc-500 mb-2 flex items-center gap-1"><Film size={13} /> Reframe</p>
                        <div className="flex gap-2">
                            {[{ v: 'auto', l: 'Smart Crop' }, { v: 'fit', l: 'Blurred Bars' }].map((opt) => (
                                <button
                                    key={opt.v}
                                    type="button"
                                    onClick={() => setLayout(opt.v)}
                                    className={`flex-1 py-2 rounded-lg border text-sm font-medium transition-all ${layout === opt.v
                                        ? 'border-primary/50 bg-primary/10 text-primary'
                                        : 'border-white/10 bg-white/5 text-zinc-400 hover:text-white'
                                        }`}
                                >
                                    {opt.l}
                                </button>
                            ))}
                        </div>
                    </div>
                    <div className="space-y-2">
                        <p className="text-xs text-zinc-500 mb-2">Bake into every part</p>
                        <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
                            <input type="checkbox" checked={bakeHooks} onChange={(e) => setBakeHooks(e.target.checked)} className="accent-primary" />
                            Hook text overlay
                        </label>
                        <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
                            <input type="checkbox" checked={bakeSubtitles} onChange={(e) => setBakeSubtitles(e.target.checked)} className="accent-primary" />
                            <span className="flex items-center gap-1"><Captions size={14} /> Subtitles</span>
                        </label>
                    </div>
                </div>

                {bakeSubtitles && (
                    <div className="grid sm:grid-cols-4 gap-3 pt-1 border-t border-white/5">
                        <div className="pt-3">
                            <p className="text-xs text-zinc-500 mb-1">Position</p>
                            <select
                                value={subtitleStyle.position}
                                onChange={(e) => setSubtitleStyle({ ...subtitleStyle, position: e.target.value })}
                                className="input-field"
                            >
                                {SUB_POSITIONS.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}
                            </select>
                        </div>
                        <div className="pt-3">
                            <p className="text-xs text-zinc-500 mb-1">Font size</p>
                            <input
                                type="number"
                                min={8}
                                max={48}
                                value={subtitleStyle.font_size}
                                onChange={(e) => setSubtitleStyle({ ...subtitleStyle, font_size: Number(e.target.value) })}
                                className="input-field"
                            />
                        </div>
                        <div className="pt-3">
                            <p className="text-xs text-zinc-500 mb-1">Text</p>
                            <input
                                type="color"
                                value={subtitleStyle.font_color}
                                onChange={(e) => setSubtitleStyle({ ...subtitleStyle, font_color: e.target.value })}
                                className="w-full h-10 bg-white/5 border border-white/10 rounded-lg cursor-pointer"
                            />
                        </div>
                        <div className="pt-3">
                            <p className="text-xs text-zinc-500 mb-1">Outline</p>
                            <input
                                type="color"
                                value={subtitleStyle.border_color}
                                onChange={(e) => setSubtitleStyle({ ...subtitleStyle, border_color: e.target.value })}
                                className="w-full h-10 bg-white/5 border border-white/10 rounded-lg cursor-pointer"
                            />
                        </div>
                        <p className="sm:col-span-4 text-xs text-zinc-600">
                            Subtitles need words: the source is transcribed once before the parts render (a couple of minutes on a long video). Leave this off and the render skips transcription entirely — you can still add subtitles to individual parts afterwards.
                        </p>
                    </div>
                )}
            </div>

            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {parts.map((part) => (
                    <div key={part.index} className="bg-surface border border-white/5 rounded-2xl overflow-hidden flex flex-col">
                        <div className="relative bg-black/40 aspect-video flex items-center justify-center">
                            {part.thumb_url ? (
                                <img
                                    src={getApiUrl(part.thumb_url)}
                                    alt={`Part ${part.index}`}
                                    className="w-full h-full object-cover"
                                    loading="lazy"
                                />
                            ) : (
                                <span className="text-xs text-zinc-600">frame pending…</span>
                            )}
                            <span className="absolute top-2 left-2 px-2 py-0.5 rounded-md bg-black/70 text-xs font-medium text-white">
                                {part.index}
                            </span>
                            <span className="absolute bottom-2 right-2 px-2 py-0.5 rounded-md bg-black/70 text-xs text-zinc-300">
                                {timecode(part.end - part.start)}
                            </span>
                        </div>

                        <div className="p-3 space-y-2 flex-1 flex flex-col">
                            <div className="flex items-center gap-2 text-xs text-zinc-500">
                                <span className="w-8 shrink-0">In</span>
                                <button type="button" onClick={() => nudge(part, 'start', -5)} className="px-2 py-0.5 rounded bg-white/5 hover:bg-white/10">−5s</button>
                                <span className="font-mono text-zinc-300">{timecode(part.start)}</span>
                                <button type="button" onClick={() => nudge(part, 'start', 5)} className="px-2 py-0.5 rounded bg-white/5 hover:bg-white/10">+5s</button>
                            </div>
                            <div className="flex items-center gap-2 text-xs text-zinc-500">
                                <span className="w-8 shrink-0">Out</span>
                                <button type="button" onClick={() => nudge(part, 'end', -5)} className="px-2 py-0.5 rounded bg-white/5 hover:bg-white/10">−5s</button>
                                <span className="font-mono text-zinc-300">{timecode(part.end)}</span>
                                <button type="button" onClick={() => nudge(part, 'end', 5)} className="px-2 py-0.5 rounded bg-white/5 hover:bg-white/10">+5s</button>
                            </div>

                            <input
                                type="text"
                                value={part.title || ''}
                                onChange={(e) => editPart(part.index, { title: e.target.value, title_locked: true })}
                                placeholder="Title"
                                className="input-field text-sm"
                            />
                            <input
                                type="text"
                                value={part.hook || ''}
                                onChange={(e) => editPart(part.index, { hook: e.target.value, hook_locked: true })}
                                placeholder="Hook text"
                                className="input-field text-sm"
                            />

                            <div className="flex items-center justify-between pt-1 mt-auto">
                                <button
                                    type="button"
                                    onClick={() => resetOverrides(part.index)}
                                    title="Back to the templates"
                                    className="flex items-center gap-1 text-xs text-zinc-500 hover:text-white"
                                >
                                    <RotateCcw size={13} />
                                    Reset text
                                </button>
                                <button
                                    type="button"
                                    onClick={() => removePart(part.index)}
                                    title="Drop this part"
                                    className="flex items-center gap-1 text-xs text-zinc-500 hover:text-red-400"
                                >
                                    <Trash2 size={13} />
                                    Remove
                                </button>
                            </div>
                        </div>
                    </div>
                ))}
            </div>

            <div className="flex justify-end pb-8">
                <button
                    onClick={submit}
                    disabled={busy || !parts.length}
                    className="btn-primary flex items-center gap-2"
                >
                    <Play size={18} />
                    Render {parts.length} parts
                </button>
            </div>
        </div>
    );
}
