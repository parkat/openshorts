import React, { useState, useEffect } from 'react';
import { Crop, X, Loader2, AlertCircle } from 'lucide-react';
import { getApiUrl } from '../config';

// Manual crop editor (v1): reposition + zoom a 9:16 crop window over the retained
// 16:9 source, then re-render the clip. The overlay math mirrors the backend:
//   crop height fraction = 1/zoom ; crop is 9:16, so on a 16:9 preview the box is
//   width% = (9/16)^2 * 100 / zoom ; x/y are 0..1 of the remaining space.
const WIDTH_PCT_AT_FULL = (9 / 16) * (9 / 16) * 100; // ≈ 31.64

export default function CropModal({ isOpen, onClose, jobId, clipIndex, onApply }) {
    const [loading, setLoading] = useState(true);
    const [available, setAvailable] = useState(false);
    const [sourceUrl, setSourceUrl] = useState(null);
    const [zoom, setZoom] = useState(1.0);
    const [x, setX] = useState(0.5);
    const [y, setY] = useState(0.5);
    const [applying, setApplying] = useState(false);
    const [error, setError] = useState(null);

    useEffect(() => {
        if (!isOpen) return;
        setLoading(true);
        setError(null);
        setZoom(1.0); setX(0.5); setY(0.5);
        fetch(getApiUrl(`/api/clip/${jobId}/${clipIndex}/source`))
            .then((r) => (r.ok ? r.json() : { available: false }))
            .then((d) => {
                setAvailable(!!d.available);
                setSourceUrl(d.source_url ? getApiUrl(d.source_url) : null);
            })
            .catch(() => setAvailable(false))
            .finally(() => setLoading(false));
    }, [isOpen, jobId, clipIndex]);

    if (!isOpen) return null;

    const heightPct = 100 / zoom;
    const widthPct = WIDTH_PCT_AT_FULL / zoom;
    const leftPct = x * (100 - widthPct);
    const topPct = y * (100 - heightPct);

    const handleApply = async () => {
        setApplying(true);
        setError(null);
        try {
            const res = await fetch(getApiUrl('/api/recrop'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job_id: jobId, clip_index: clipIndex, x, y, zoom }),
            });
            if (!res.ok) {
                const t = await res.text();
                try { throw new Error(JSON.parse(t).detail || t); } catch (e) { throw new Error(t); }
            }
            const data = await res.json();
            if (data.new_video_url) {
                onApply(getApiUrl(data.new_video_url));
                onClose();
            }
        } catch (e) {
            setError(e.message);
        } finally {
            setApplying(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
            <div
                className="bg-surface border border-white/10 rounded-2xl w-full max-w-md p-5 shadow-2xl"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-center justify-between mb-4">
                    <h3 className="flex items-center gap-2 text-sm font-bold text-white">
                        <Crop size={16} className="text-primary" /> Adjust Crop
                    </h3>
                    <button onClick={onClose} className="text-zinc-500 hover:text-white transition-colors">
                        <X size={18} />
                    </button>
                </div>

                {loading ? (
                    <div className="h-40 flex items-center justify-center text-zinc-500">
                        <Loader2 size={20} className="animate-spin" />
                    </div>
                ) : !available ? (
                    <div className="p-3 bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs rounded-lg flex items-start gap-2">
                        <AlertCircle size={14} className="shrink-0 mt-0.5" />
                        <span>Original footage isn't available for this clip. Manual re-crop only works on clips generated after this feature was added — regenerate the video to enable it.</span>
                    </div>
                ) : (
                    <>
                        {/* Preview: 16:9 source with the 9:16 crop box overlaid */}
                        <div className="relative w-full aspect-video rounded-lg overflow-hidden bg-black border border-white/10">
                            <video
                                src={sourceUrl}
                                className="w-full h-full object-contain"
                                autoPlay muted loop playsInline
                            />
                            <div className="absolute inset-0 pointer-events-none">
                                {/* dim outside the crop box */}
                                <div className="absolute inset-0 bg-black/50" />
                                <div
                                    className="absolute border-2 border-primary shadow-[0_0_0_2000px_rgba(0,0,0,0.5)] box-border"
                                    style={{
                                        left: `${leftPct}%`,
                                        top: `${topPct}%`,
                                        width: `${widthPct}%`,
                                        height: `${heightPct}%`,
                                    }}
                                />
                            </div>
                        </div>

                        <div className="mt-4 space-y-3">
                            <Slider label="Zoom" value={zoom} min={1} max={3} step={0.05}
                                display={`${zoom.toFixed(2)}×`} onChange={setZoom} />
                            <Slider label="Horizontal" value={x} min={0} max={1} step={0.01}
                                display={x < 0.4 ? 'Left' : x > 0.6 ? 'Right' : 'Center'} onChange={setX} />
                            <Slider label="Vertical" value={y} min={0} max={1} step={0.01}
                                display={zoom <= 1.001 ? '—' : (y < 0.4 ? 'Top' : y > 0.6 ? 'Bottom' : 'Center')}
                                onChange={setY} disabled={zoom <= 1.001} />
                        </div>

                        {error && (
                            <div className="mt-3 p-2 bg-red-500/10 border border-red-500/20 text-red-400 text-[11px] rounded-lg flex items-center gap-2">
                                <AlertCircle size={12} className="shrink-0" /> {error}
                            </div>
                        )}

                        <button
                            onClick={handleApply}
                            disabled={applying}
                            className="w-full mt-4 py-2 bg-primary hover:bg-blue-600 text-white rounded-lg text-sm font-bold transition-all active:scale-[0.98] flex items-center justify-center gap-2 disabled:opacity-60"
                        >
                            {applying ? <><Loader2 size={16} className="animate-spin" /> Re-rendering…</> : <>Apply Crop</>}
                        </button>
                    </>
                )}
            </div>
        </div>
    );
}

function Slider({ label, value, min, max, step, display, onChange, disabled }) {
    return (
        <div className={disabled ? 'opacity-40' : ''}>
            <div className="flex justify-between text-xs text-zinc-400 mb-1">
                <span>{label}</span>
                <span className="text-zinc-500">{display}</span>
            </div>
            <input
                type="range"
                min={min} max={max} step={step} value={value}
                disabled={disabled}
                onChange={(e) => onChange(parseFloat(e.target.value))}
                className="w-full accent-primary cursor-pointer"
            />
        </div>
    );
}
