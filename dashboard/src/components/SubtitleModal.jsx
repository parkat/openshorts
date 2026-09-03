import React, { useState, useEffect, lazy, Suspense } from 'react';
import { X, Type, Loader2, Save, Trash2, Bookmark } from 'lucide-react';
import { getApiUrl } from '../config';
import { buildSubtitleConfig, positionZone, ffMarginV } from '../lib/subtitleConfig';
import { listPresets, savePreset, deletePreset } from '../lib/presetsApi';

// Remotion's <Player> is ~184KB — a quarter of the JS bundle — and is only ever
// seen inside this modal. Loading it on demand keeps it out of the initial parse
// on every page view; the modal itself opens instantly and the preview fades in.
const RemotionPreview = React.lazy(() => import('./RemotionPreview'));

const FONT_OPTIONS = [
    { value: 'Verdana', label: 'Verdana' },
    { value: 'Arial', label: 'Arial' },
    { value: 'Impact', label: 'Impact' },
    { value: 'Helvetica', label: 'Helvetica' },
    { value: 'Georgia', label: 'Georgia' },
    { value: 'Courier New', label: 'Courier New' },
];

const COLOR_PRESETS = [
    { color: '#FFFFFF', label: 'White' },
    { color: '#FFFF00', label: 'Yellow' },
    { color: '#00FFFF', label: 'Cyan' },
    { color: '#00FF00', label: 'Green' },
    { color: '#FF0000', label: 'Red' },
    { color: '#FF69B4', label: 'Pink' },
];

const ANIMATION_OPTIONS = [
    { value: 'pop', label: 'Pop' },
    { value: 'word-highlight', label: 'Glow' },
    { value: 'karaoke', label: 'Karaoke' },
    { value: 'none', label: 'None' },
];

export default function SubtitleModal({ isOpen, onClose, onGenerate, isProcessing, videoUrl, jobId, clipIndex, existingHook }) {
    const [positionY, setPositionY] = useState(85); // vertical %, 0=top .. 100=bottom (single source of truth)
    const [fontSize, setFontSize] = useState(28);
    const [fontName, setFontName] = useState('Verdana');
    const [fontColor, setFontColor] = useState('#FFFFFF');
    const [highlightColor, setHighlightColor] = useState('#FFDD00');
    const [borderColor, setBorderColor] = useState('#000000');
    const [borderWidth, setBorderWidth] = useState(2);
    const [bgColor, setBgColor] = useState('#000000');
    const [bgOpacity, setBgOpacity] = useState(0.0);
    const [animation, setAnimation] = useState('pop');
    const [showTextEditor, setShowTextEditor] = useState(false);

    // Preset library (backend-synced, shared with the batch bar)
    const [presets, setPresets] = useState([]);
    const [presetId, setPresetId] = useState('');

    const currentSettings = () => ({
        positionY, fontSize, fontName, fontColor, highlightColor,
        borderColor, borderWidth, bgColor, bgOpacity, animation,
    });
    const applySettings = (s) => {
        if (!s) return;
        if (s.positionY !== undefined) setPositionY(s.positionY);
        if (s.fontSize !== undefined) setFontSize(s.fontSize);
        if (s.fontName !== undefined) setFontName(s.fontName);
        if (s.fontColor !== undefined) setFontColor(s.fontColor);
        if (s.highlightColor !== undefined) setHighlightColor(s.highlightColor);
        if (s.borderColor !== undefined) setBorderColor(s.borderColor);
        if (s.borderWidth !== undefined) setBorderWidth(s.borderWidth);
        if (s.bgColor !== undefined) setBgColor(s.bgColor);
        if (s.bgOpacity !== undefined) setBgOpacity(s.bgOpacity);
        if (s.animation !== undefined) setAnimation(s.animation);
    };

    const refreshPresets = () => listPresets().then(setPresets).catch(() => {});
    useEffect(() => { if (isOpen) refreshPresets(); }, [isOpen]);

    const handleLoadPreset = (id) => {
        setPresetId(id);
        const p = presets.find((x) => x.id === id);
        if (p) applySettings(p.settings);
    };
    const handleSavePreset = async () => {
        const name = window.prompt('Save subtitle preset as:');
        if (!name || !name.trim()) return;
        try {
            const saved = await savePreset({ name: name.trim(), kind: 'subtitle', settings: currentSettings() });
            await refreshPresets();
            if (saved?.id) setPresetId(saved.id);
        } catch (e) { alert('Could not save preset: ' + e.message); }
    };
    const handleDeletePreset = async () => {
        const p = presets.find((x) => x.id === presetId);
        if (!p || !window.confirm(`Delete preset "${p.name}"?`)) return;
        try { await deletePreset(presetId); setPresetId(''); await refreshPresets(); }
        catch (e) { alert('Could not delete preset: ' + e.message); }
    };

    // Remotion preview state
    const [captions, setCaptions] = useState([]);
    const [originalCaptions, setOriginalCaptions] = useState([]);
    const [editableText, setEditableText] = useState('');
    const [durationSec, setDurationSec] = useState(30);
    const [captionsLoading, setCaptionsLoading] = useState(false);
    const [useRemotionPreview, setUseRemotionPreview] = useState(false);

    // Fetch word-level captions when modal opens
    useEffect(() => {
        if (!isOpen || !jobId || clipIndex === undefined) return;

        setCaptionsLoading(true);
        fetch(getApiUrl(`/api/clip/${jobId}/${clipIndex}/transcript`))
            .then((res) => res.ok ? res.json() : null)
            .then((data) => {
                if (data && data.captions && data.captions.length > 0) {
                    setCaptions(data.captions);
                    setOriginalCaptions(data.captions);
                    setEditableText(data.captions.map(c => c.text).join(' '));
                    setDurationSec(data.durationSec || 30);
                    setUseRemotionPreview(true);
                } else {
                    setUseRemotionPreview(false);
                }
            })
            .catch(() => setUseRemotionPreview(false))
            .finally(() => setCaptionsLoading(false));
    }, [isOpen, jobId, clipIndex]);

    // When user edits text, redistribute words across original timestamps
    const handleTextEdit = (newText) => {
        setEditableText(newText);
        const newWords = newText.split(/\s+/).filter(w => w.length > 0);
        if (newWords.length === 0 || originalCaptions.length === 0) {
            setCaptions([]);
            return;
        }

        // Distribute new words across the time span of original captions
        const totalDurationMs = originalCaptions[originalCaptions.length - 1].endMs - originalCaptions[0].startMs;
        const startMs = originalCaptions[0].startMs;
        const wordDurationMs = totalDurationMs / newWords.length;

        const newCaptions = newWords.map((word, i) => ({
            text: word,
            startMs: Math.round(startMs + i * wordDurationMs),
            endMs: Math.round(startMs + (i + 1) * wordDurationMs),
        }));
        setCaptions(newCaptions);
    };

    if (!isOpen) return null;

    // Coarse zone + FFmpeg fallback margin + Remotion config (shared with batch).
    const zone = positionZone(positionY);
    const marginV = ffMarginV(positionY);
    const subtitleConfig = buildSubtitleConfig(currentSettings(), captions);

    // Fallback: static CSS preview (same as original)
    const bw = Math.max(borderWidth, 0);
    const bc = borderColor;
    const outlineShadow = bw > 0 ? [
        `-${bw}px -${bw}px 0 ${bc}`, `${bw}px -${bw}px 0 ${bc}`,
        `-${bw}px ${bw}px 0 ${bc}`, `${bw}px ${bw}px 0 ${bc}`,
        `0 -${bw}px 0 ${bc}`, `0 ${bw}px 0 ${bc}`,
        `-${bw}px 0 0 ${bc}`, `${bw}px 0 0 ${bc}`,
    ].join(', ') : 'none';

    const fallbackPreviewStyle = {
        fontFamily: fontName,
        color: fontColor,
        fontSize: '20px',
        fontWeight: 'bold',
        maxWidth: '85%',
        padding: '6px 12px',
        borderRadius: '4px',
        textAlign: 'center',
        lineHeight: '1.3',
        ...(bgOpacity > 0
            ? {
                backgroundColor: `${bgColor}${Math.round(bgOpacity * 255).toString(16).padStart(2, '0')}`,
                textShadow: 'none',
            }
            : { textShadow: outlineShadow }
        ),
    };

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-[fadeIn_0.2s_ease-out]">
            <div className="bg-[#121214] border border-white/10 p-6 rounded-2xl w-full max-w-5xl shadow-2xl relative flex flex-col md:flex-row gap-6 max-h-[90vh]">
                <button
                    onClick={onClose}
                    className="absolute top-4 right-4 text-zinc-500 hover:text-white z-10"
                >
                    <X size={20} />
                </button>

                {/* Left: Preview */}
                <div className="flex-1 flex flex-col items-center justify-center bg-black rounded-lg border border-white/5 overflow-hidden relative aspect-[9/16] max-h-[600px]">
                    {captionsLoading ? (
                        <div className="flex items-center gap-2 text-zinc-400">
                            <Loader2 size={16} className="animate-spin" />
                            <span className="text-sm">Loading preview...</span>
                        </div>
                    ) : useRemotionPreview ? (
                        <Suspense fallback={<div className="flex items-center gap-2 text-zinc-500 text-sm"><Loader2 size={16} className="animate-spin" /> Loading preview…</div>}>
                            <RemotionPreview
                                videoUrl={videoUrl}
                                durationInSeconds={durationSec}
                                subtitles={subtitleConfig}
                                hook={existingHook || null}
                            />
                        </Suspense>
                    ) : (
                        <>
                            <video src={videoUrl} className="w-full h-full object-contain opacity-50" muted playsInline />
                            <div className="absolute left-0 right-0 px-8 text-center transition-all duration-150 pointer-events-none flex flex-col items-center justify-center"
                                style={{ top: `${positionY}%`, transform: 'translateY(-50%)' }}>
                                <span style={fallbackPreviewStyle}>
                                    This is how your subtitles<br/>will appear on the video
                                </span>
                            </div>
                        </>
                    )}
                </div>

                {/* Right: Controls */}
                <div className="w-full md:w-80 flex flex-col">
                    <h3 className="text-xl font-bold text-white mb-4 flex items-center gap-2 shrink-0">
                        <Type className="text-primary" /> Auto Subtitles
                    </h3>

                    {/* Preset bar: load / save / delete (synced across devices) */}
                    <div className="flex items-center gap-2 mb-4 shrink-0">
                        <Bookmark size={14} className="text-primary shrink-0" />
                        <select
                            value={presetId}
                            onChange={(e) => handleLoadPreset(e.target.value)}
                            className="flex-1 min-w-0 bg-black/40 border border-white/10 rounded-lg p-2 text-xs text-white focus:outline-none focus:border-primary/50"
                        >
                            <option value="">Load preset…</option>
                            {presets.map((p) => (<option key={p.id} value={p.id}>{p.name}</option>))}
                        </select>
                        <button type="button" onClick={handleSavePreset} title="Save current settings as a preset"
                            className="p-2 rounded-lg bg-white/5 border border-white/10 text-zinc-300 hover:text-white hover:bg-white/10 shrink-0">
                            <Save size={14} />
                        </button>
                        {presetId && (
                            <button type="button" onClick={handleDeletePreset} title="Delete this preset"
                                className="p-2 rounded-lg bg-white/5 border border-white/10 text-zinc-400 hover:text-red-400 hover:bg-white/10 shrink-0">
                                <Trash2 size={14} />
                            </button>
                        )}
                    </div>

                    <div className="space-y-5 flex-1 overflow-y-auto custom-scrollbar pr-1">
                        {/* Position: presets + fine vertical slider */}
                        <div>
                            <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2 block">Position</label>
                            <div className="grid grid-cols-3 gap-2 mb-2">
                                {[{ k: 'top', v: 12 }, { k: 'middle', v: 50 }, { k: 'bottom', v: 88 }].map((p) => (
                                    <button
                                        key={p.k}
                                        onClick={() => setPositionY(p.v)}
                                        className={`p-2 rounded-lg border text-center text-xs font-medium transition-all ${zone === p.k ? 'bg-primary/20 border-primary text-white' : 'bg-white/5 border-white/5 text-zinc-400 hover:bg-white/10'}`}
                                    >
                                        {p.k.charAt(0).toUpperCase() + p.k.slice(1)}
                                    </button>
                                ))}
                            </div>
                            <input
                                type="range" min="0" max="100" value={positionY}
                                onChange={(e) => setPositionY(parseInt(e.target.value))}
                                className="w-full accent-primary"
                            />
                            <div className="flex justify-between text-[10px] text-zinc-500">
                                <span>Top</span><span>{positionY}%</span><span>Bottom</span>
                            </div>
                        </div>

                        {/* Text Size */}
                        <div>
                            <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2 block">Text Size</label>
                            <input
                                type="range" min="14" max="44" value={fontSize}
                                onChange={(e) => setFontSize(parseInt(e.target.value))}
                                className="w-full accent-primary"
                            />
                            <div className="flex justify-between text-[10px] text-zinc-500">
                                <span>Small</span><span>{fontSize}px</span><span>Large</span>
                            </div>
                        </div>

                        {/* Animation Style (new) */}
                        <div>
                            <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2 block">Animation</label>
                            <div className="grid grid-cols-2 gap-2">
                                {ANIMATION_OPTIONS.map((opt) => (
                                    <button
                                        key={opt.value}
                                        onClick={() => setAnimation(opt.value)}
                                        className={`p-2 rounded-lg border text-center text-xs font-medium transition-all ${animation === opt.value ? 'bg-primary/20 border-primary text-white' : 'bg-white/5 border-white/5 text-zinc-400 hover:bg-white/10'}`}
                                    >
                                        {opt.label}
                                    </button>
                                ))}
                            </div>
                        </div>

                        {/* Editable Transcript (collapsible) */}
                        {useRemotionPreview && (
                            <div>
                                <button
                                    type="button"
                                    onClick={() => setShowTextEditor(!showTextEditor)}
                                    className="w-full flex items-center justify-between text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2"
                                >
                                    <span>Edit Text ({captions.length} words)</span>
                                    <span className={`transition-transform ${showTextEditor ? 'rotate-180' : ''}`}>▾</span>
                                </button>
                                {showTextEditor && (
                                    <textarea
                                        value={editableText}
                                        onChange={(e) => handleTextEdit(e.target.value)}
                                        rows={5}
                                        className="w-full bg-black/40 border border-white/10 rounded-lg p-2.5 text-sm text-white focus:outline-none focus:border-primary/50 resize-none leading-relaxed animate-[fadeIn_0.15s_ease-out]"
                                        placeholder="Edit subtitle text..."
                                    />
                                )}
                            </div>
                        )}

                        {/* Font Family */}
                        <div>
                            <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2 block">Font</label>
                            <select
                                value={fontName}
                                onChange={(e) => setFontName(e.target.value)}
                                className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-primary/50"
                            >
                                {FONT_OPTIONS.map((f) => (
                                    <option key={f.value} value={f.value} style={{ fontFamily: f.value }}>{f.label}</option>
                                ))}
                            </select>
                        </div>

                        {/* Text Color */}
                        <div>
                            <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2 block">Text Color</label>
                            <div className="flex flex-wrap gap-2">
                                {COLOR_PRESETS.map((c) => (
                                    <button
                                        key={c.color}
                                        onClick={() => setFontColor(c.color)}
                                        className={`w-7 h-7 rounded-full border-2 transition-all ${fontColor === c.color ? 'border-white scale-110' : 'border-white/20 hover:border-white/50'}`}
                                        style={{ backgroundColor: c.color }}
                                        title={c.label}
                                    />
                                ))}
                                <label className="w-7 h-7 rounded-full border-2 border-dashed border-white/20 cursor-pointer flex items-center justify-center hover:border-white/50 transition-all overflow-hidden relative" title="Custom color">
                                    <span className="text-[10px] text-zinc-400">+</span>
                                    <input type="color" value={fontColor} onChange={(e) => setFontColor(e.target.value)} className="absolute inset-0 opacity-0 cursor-pointer" />
                                </label>
                            </div>
                        </div>

                        {/* Highlight Color (new) */}
                        <div>
                            <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2 block">Highlight Color</label>
                            <div className="flex flex-wrap gap-2">
                                {[{ color: '#FFDD00', label: 'Gold' }, { color: '#FF4444', label: 'Red' }, { color: '#00FF88', label: 'Green' }, { color: '#00BBFF', label: 'Blue' }, { color: '#FF69B4', label: 'Pink' }].map((c) => (
                                    <button
                                        key={c.color}
                                        onClick={() => setHighlightColor(c.color)}
                                        className={`w-7 h-7 rounded-full border-2 transition-all ${highlightColor === c.color ? 'border-white scale-110' : 'border-white/20 hover:border-white/50'}`}
                                        style={{ backgroundColor: c.color }}
                                        title={c.label}
                                    />
                                ))}
                            </div>
                        </div>

                        {/* Border / Outline */}
                        <div>
                            <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2 block">Border</label>
                            <div className="flex items-center gap-3">
                                <label className="relative w-8 h-8 rounded-lg border border-white/10 cursor-pointer overflow-hidden shrink-0" title="Border color">
                                    <div className="w-full h-full" style={{ backgroundColor: borderColor }} />
                                    <input type="color" value={borderColor} onChange={(e) => setBorderColor(e.target.value)} className="absolute inset-0 opacity-0 cursor-pointer" />
                                </label>
                                <div className="flex-1">
                                    <input
                                        type="range"
                                        min="0"
                                        max="5"
                                        value={borderWidth}
                                        onChange={(e) => setBorderWidth(parseInt(e.target.value))}
                                        className="w-full accent-primary"
                                    />
                                    <div className="flex justify-between text-[10px] text-zinc-500">
                                        <span>None</span>
                                        <span>Thick</span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Background Box */}
                        <div>
                            <div className="flex items-center justify-between mb-2">
                                <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider">Background Box</label>
                                <label className="relative inline-flex items-center cursor-pointer">
                                    <input type="checkbox" checked={bgOpacity > 0} onChange={(e) => setBgOpacity(e.target.checked ? 0.5 : 0)} className="sr-only peer" />
                                    <div className="w-8 h-4 bg-zinc-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[0px] after:left-[0px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-primary"></div>
                                </label>
                            </div>
                            {bgOpacity > 0 && (
                                <div className="space-y-3 animate-[fadeIn_0.2s_ease-out]">
                                    <div className="flex items-center gap-3">
                                        <label className="relative w-8 h-8 rounded-lg border border-white/10 cursor-pointer overflow-hidden shrink-0" title="Background color">
                                            <div className="w-full h-full" style={{ backgroundColor: bgColor }} />
                                            <input type="color" value={bgColor} onChange={(e) => setBgColor(e.target.value)} className="absolute inset-0 opacity-0 cursor-pointer" />
                                        </label>
                                        <div className="flex-1">
                                            <input
                                                type="range"
                                                min="10"
                                                max="100"
                                                value={Math.round(bgOpacity * 100)}
                                                onChange={(e) => setBgOpacity(parseInt(e.target.value) / 100)}
                                                className="w-full accent-primary"
                                            />
                                            <div className="flex justify-between text-[10px] text-zinc-500">
                                                <span>Transparent</span>
                                                <span>{Math.round(bgOpacity * 100)}%</span>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>

                    <button
                        onClick={() => onGenerate({
                            position: zone, positionY, margin_v: marginV,
                            fontSize, fontName, fontColor, borderColor, borderWidth, bgColor, bgOpacity,
                            settings: currentSettings(),
                            // Remotion data
                            remotion: useRemotionPreview ? subtitleConfig : null,
                        })}
                        disabled={isProcessing}
                        className="w-full py-3 mt-4 bg-gradient-to-r from-yellow-500 to-orange-500 hover:from-yellow-400 hover:to-orange-400 text-black font-bold rounded-xl shadow-lg shadow-orange-500/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2 shrink-0"
                    >
                        {isProcessing ? <Loader2 size={20} className="animate-spin" /> : <Type size={20} />}
                        {isProcessing ? 'Generating...' : 'Generate Subtitles'}
                    </button>
                </div>
            </div>
        </div>
    );
}
