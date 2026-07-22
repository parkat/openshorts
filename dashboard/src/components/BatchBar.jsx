import React, { useState } from 'react';
import { Download, Play, X, Loader2, Type, Wand2, Sparkles, Layers } from 'lucide-react';
import { DEFAULT_SUBTITLE_SETTINGS } from '../lib/subtitleConfig';

// Batch action bar. Appears above the clips grid; acts on the user's SELECTED
// clips only. Lets you apply chosen edits (subtitles via a preset, optional hook
// / auto-edit) across the selection and download them as one zip.
function EditToggle({ active, onClick, icon: Icon, label }) {
    return (
        <button
            type="button"
            onClick={onClick}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-semibold transition-all ${active ? 'bg-primary/20 border-primary text-white' : 'bg-white/5 border-white/10 text-zinc-400 hover:bg-white/10'}`}
        >
            <Icon size={13} /> {label}
        </button>
    );
}

export default function BatchBar({
    selectedCount, totalCount, onToggleSelectAll,
    subtitlePresets = [], batch, onApply, onDownload, onCancel,
}) {
    const [doSubtitles, setDoSubtitles] = useState(true);
    const [presetId, setPresetId] = useState('');
    const [doHook, setDoHook] = useState(false);
    const [doAutoEdit, setDoAutoEdit] = useState(false);

    const running = !!batch?.running;
    const allSelected = totalCount > 0 && selectedCount === totalCount;
    const preset = subtitlePresets.find((p) => p.id === presetId);
    const anyEdit = doSubtitles || doHook || doAutoEdit;
    const canApply = selectedCount > 0 && !running && anyEdit;

    const handleApply = () => onApply({
        subtitleSettings: doSubtitles ? (preset ? preset.settings : DEFAULT_SUBTITLE_SETTINGS) : null,
        doHook,
        doAutoEdit,
    });

    return (
        <div className="mb-4 rounded-xl border border-white/10 bg-[#141416] p-3 flex flex-wrap items-center gap-x-3 gap-y-2 shrink-0">
            {/* Selection summary */}
            <div className="flex items-center gap-2">
                <Layers size={16} className="text-primary" />
                <span className="text-sm font-bold text-white">{selectedCount} selected</span>
                <button
                    type="button"
                    onClick={onToggleSelectAll}
                    className="text-xs text-zinc-400 hover:text-white underline underline-offset-2"
                >
                    {allSelected ? 'Clear' : `Select all ${totalCount}`}
                </button>
            </div>

            <div className="h-5 w-px bg-white/10 hidden sm:block" />

            {/* Which edits to apply */}
            <div className="flex items-center gap-2 flex-wrap">
                <EditToggle active={doSubtitles} onClick={() => setDoSubtitles(v => !v)} icon={Type} label="Subtitles" />
                {doSubtitles && (
                    <select
                        value={presetId}
                        onChange={(e) => setPresetId(e.target.value)}
                        className="bg-black/40 border border-white/10 rounded-lg py-1.5 px-2 text-xs text-white focus:outline-none focus:border-primary/50 max-w-[180px]"
                        title="Subtitle style"
                    >
                        <option value="">Default style</option>
                        {subtitlePresets.map((p) => (<option key={p.id} value={p.id}>{p.name}</option>))}
                    </select>
                )}
                <EditToggle active={doHook} onClick={() => setDoHook(v => !v)} icon={Wand2} label="Hook" />
                <EditToggle active={doAutoEdit} onClick={() => setDoAutoEdit(v => !v)} icon={Sparkles} label="Auto-Edit" />
            </div>

            <div className="flex items-center gap-2 ml-auto">
                {running ? (
                    <>
                        <span className="text-xs text-zinc-300 flex items-center gap-2">
                            <Loader2 size={14} className="animate-spin text-primary" />
                            {batch.stage || `Rendering ${batch.done}/${batch.total}…`}
                        </span>
                        <button
                            type="button"
                            onClick={onCancel}
                            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-zinc-300 hover:text-white hover:bg-white/10 text-xs font-semibold"
                        >
                            <X size={13} /> Cancel
                        </button>
                    </>
                ) : (
                    <>
                        <button
                            type="button"
                            onClick={handleApply}
                            disabled={!canApply}
                            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-gradient-to-r from-yellow-500 to-orange-500 hover:from-yellow-400 hover:to-orange-400 text-black text-xs font-bold disabled:opacity-40 disabled:cursor-not-allowed transition-all"
                        >
                            <Play size={13} /> Apply to {selectedCount}
                        </button>
                        <button
                            type="button"
                            onClick={onDownload}
                            disabled={selectedCount === 0}
                            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-zinc-200 hover:bg-white/10 text-xs font-semibold disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                            <Download size={13} /> Download .zip
                        </button>
                    </>
                )}
            </div>

            {batch?.error && (
                <div className="w-full text-xs text-red-400 flex items-center gap-1.5">
                    <X size={12} /> {batch.error}
                </div>
            )}
        </div>
    );
}
