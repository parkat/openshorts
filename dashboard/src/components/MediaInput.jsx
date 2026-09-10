import React, { useState, useEffect } from 'react';
import { Youtube, Upload, FileVideo, X, Scissors, Sparkles, HardDrive, RefreshCw, Eye } from 'lucide-react';
import { getApiUrl } from '../config';

export default function MediaInput({ onProcess, onPlan, isProcessing }) {
    const [youtubeUrlEnabled, setYoutubeUrlEnabled] = useState(true);
    const [localMediaEnabled, setLocalMediaEnabled] = useState(false);
    const [maxUploadMb, setMaxUploadMb] = useState(2048);
    const [mode, setMode] = useState('url'); // 'url' | 'file' | 'server'
    const [url, setUrl] = useState('');
    const [file, setFile] = useState(null);
    const [serverPath, setServerPath] = useState('');
    const [serverFiles, setServerFiles] = useState([]);
    const [serverRoots, setServerRoots] = useState([]);
    const [loadingLibrary, setLoadingLibrary] = useState(false);
    const [libraryError, setLibraryError] = useState('');
    const [acknowledged, setAcknowledged] = useState(false);
    const [clipMode, setClipMode] = useState('viral');   // 'viral' | 'split'
    const [partLength, setPartLength] = useState(60);    // 60 | 90 | 180
    const [layout, setLayout] = useState('auto');        // 'auto' (smart crop) | 'fit' (blurred bars)

    useEffect(() => {
        fetch(getApiUrl('/api/config'))
            .then((r) => r.ok ? r.json() : null)
            .then((cfg) => {
                if (!cfg) return;
                if (cfg.youtubeUrlEnabled === false) {
                    setYoutubeUrlEnabled(false);
                    setMode('file');
                }
                if (cfg.localMediaEnabled) setLocalMediaEnabled(true);
                if (cfg.maxUploadMb) setMaxUploadMb(cfg.maxUploadMb);
            })
            .catch(() => {});
    }, []);

    const loadLibrary = () => {
        setLoadingLibrary(true);
        setLibraryError('');
        fetch(getApiUrl('/api/local-media'))
            .then((r) => r.ok ? r.json() : Promise.reject(new Error('Could not read the server media directories.')))
            .then((data) => {
                setServerFiles(data.files || []);
                setServerRoots(data.roots || []);
            })
            .catch((e) => setLibraryError(e.message))
            .finally(() => setLoadingLibrary(false));
    };

    useEffect(() => {
        if (mode === 'server' && !serverFiles.length && !loadingLibrary) loadLibrary();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [mode]);

    // Normalize a pasted link: trim whitespace and auto-prepend https:// when the
    // user omitted the scheme (common when copying "www.youtube.com/..."). This is
    // why the old type="url" field rejected valid-looking links with "Please enter a URL".
    const normalizeUrl = (raw) => {
        const t = (raw || '').trim();
        if (!t) return '';
        return /^https?:\/\//i.test(t) ? t : `https://${t}`;
    };

    // A server-side file in split mode goes to the planner first: on a two-hour
    // source you want to see the forty parts, and name them, before committing
    // hours of rendering to them.
    const wantsPlanner = mode === 'server' && clipMode === 'split' && !!onPlan;

    const handleSubmit = (e) => {
        e.preventDefault();
        if (!acknowledged) return;
        if (mode === 'url') {
            const cleanUrl = normalizeUrl(url);
            if (!cleanUrl) return;
            onProcess({ type: 'url', payload: cleanUrl, acknowledged: true, clipMode, partLength, layout });
        } else if (mode === 'file' && file) {
            onProcess({ type: 'file', payload: file, acknowledged: true, clipMode, partLength, layout });
        } else if (mode === 'server' && serverPath.trim()) {
            const localPath = serverPath.trim();
            if (wantsPlanner) {
                onPlan({ localPath, partLength, layout, acknowledged: true });
            } else {
                onProcess({ type: 'local', payload: localPath, acknowledged: true, clipMode, partLength, layout });
            }
        }
    };

    const handleDrop = (e) => {
        e.preventDefault();
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            setFile(e.dataTransfer.files[0]);
            setMode('file');
        }
    };

    const tabClass = (id) => `flex items-center gap-2 pb-2 px-2 transition-all ${mode === id
        ? 'text-primary border-b-2 border-primary -mb-[17px]'
        : 'text-zinc-400 hover:text-white'
        }`;

    const prettySize = (mb) => (mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`);

    return (
        <div className="bg-surface border border-white/5 rounded-2xl p-6 animate-[fadeIn_0.6s_ease-out]">
            <div className="flex gap-4 mb-6 border-b border-white/5 pb-4">
                {youtubeUrlEnabled && (
                    <button onClick={() => setMode('url')} className={tabClass('url')}>
                        <Youtube size={18} />
                        YouTube URL
                    </button>
                )}
                <button onClick={() => setMode('file')} className={tabClass('file')}>
                    <Upload size={18} />
                    Upload File
                </button>
                {localMediaEnabled && (
                    <button onClick={() => setMode('server')} className={tabClass('server')}>
                        <HardDrive size={18} />
                        Server File
                    </button>
                )}
            </div>

            <div className="flex gap-1 mb-4 p-1 bg-white/5 border border-white/10 rounded-xl">
                <button
                    type="button"
                    onClick={() => setClipMode('viral')}
                    className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-sm font-medium transition-all ${clipMode === 'viral'
                        ? 'bg-primary/15 text-primary'
                        : 'text-zinc-400 hover:text-white'
                        }`}
                >
                    <Sparkles size={16} />
                    Viral Moments
                </button>
                <button
                    type="button"
                    onClick={() => setClipMode('split')}
                    className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-sm font-medium transition-all ${clipMode === 'split'
                        ? 'bg-primary/15 text-primary'
                        : 'text-zinc-400 hover:text-white'
                        }`}
                >
                    <Scissors size={16} />
                    Split into Parts
                </button>
            </div>

            {clipMode === 'split' && (
                <div className="mb-4">
                    <p className="text-xs text-zinc-500 mb-2">Part length</p>
                    <div className="flex gap-2">
                        {[{ v: 60, l: '60s' }, { v: 90, l: '90s' }, { v: 180, l: '3 min' }].map((opt) => (
                            <button
                                key={opt.v}
                                type="button"
                                onClick={() => setPartLength(opt.v)}
                                className={`flex-1 py-2 rounded-lg border text-sm font-medium transition-all ${partLength === opt.v
                                    ? 'border-primary/50 bg-primary/10 text-primary'
                                    : 'border-white/10 bg-white/5 text-zinc-400 hover:text-white'
                                    }`}
                            >
                                {opt.l}
                            </button>
                        ))}
                    </div>
                    {wantsPlanner && (
                        <p className="text-xs text-zinc-500 mt-2">
                            You'll get a preview of every part — boundaries, titles, hooks — before anything renders.
                        </p>
                    )}
                </div>
            )}

            <div className="mb-4">
                <p className="text-xs text-zinc-500 mb-2">Reframe</p>
                <div className="flex gap-2">
                    {[
                        { v: 'auto', l: 'Smart Crop', d: 'Tracks & crops the speaker' },
                        { v: 'fit', l: 'Blurred Bars', d: 'Whole frame, blurred top/bottom' },
                    ].map((opt) => (
                        <button
                            key={opt.v}
                            type="button"
                            title={opt.d}
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

            <form onSubmit={handleSubmit}>
                {mode === 'url' && (
                    <div className="space-y-4">
                        <input
                            type="text"
                            inputMode="url"
                            value={url}
                            onChange={(e) => setUrl(e.target.value)}
                            placeholder="https://www.youtube.com/watch?v=..."
                            className="input-field"
                            required
                        />
                    </div>
                )}

                {mode === 'file' && (
                    <div
                        className={`border-2 border-dashed rounded-xl p-8 text-center transition-all ${file ? 'border-primary/50 bg-primary/5' : 'border-zinc-700 hover:border-zinc-500 bg-white/5'
                            }`}
                        onDragOver={(e) => e.preventDefault()}
                        onDrop={handleDrop}
                    >
                        {file ? (
                            <div className="flex items-center justify-center gap-3 text-white">
                                <FileVideo className="text-primary" />
                                <span className="font-medium">{file.name}</span>
                                <button
                                    type="button"
                                    onClick={() => setFile(null)}
                                    className="p-1 hover:bg-white/10 rounded-full"
                                >
                                    <X size={16} />
                                </button>
                            </div>
                        ) : (
                            <label className="cursor-pointer block">
                                <input
                                    type="file"
                                    accept="video/*"
                                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                                    className="hidden"
                                />
                                <Upload className="mx-auto mb-3 text-zinc-500" size={24} />
                                <p className="text-zinc-400">Click to upload or drag and drop</p>
                                <p className="text-xs text-zinc-600 mt-1">
                                    MP4, MOV up to {prettySize(maxUploadMb)}
                                    {localMediaEnabled && ' — for anything bigger, copy it to the box and use Server File'}
                                </p>
                            </label>
                        )}
                    </div>
                )}

                {mode === 'server' && (
                    <div className="space-y-3">
                        <div className="flex items-center justify-between">
                            <p className="text-xs text-zinc-500">
                                Files already on the server — no upload, no size limit.
                            </p>
                            <button
                                type="button"
                                onClick={loadLibrary}
                                className="flex items-center gap-1 text-xs text-zinc-400 hover:text-white"
                            >
                                <RefreshCw size={13} className={loadingLibrary ? 'animate-spin' : ''} />
                                Refresh
                            </button>
                        </div>

                        <div className="border border-white/10 rounded-xl bg-white/5 max-h-56 overflow-y-auto divide-y divide-white/5">
                            {loadingLibrary && (
                                <p className="p-4 text-sm text-zinc-500">Reading the media directories…</p>
                            )}
                            {!loadingLibrary && libraryError && (
                                <p className="p-4 text-sm text-red-400">{libraryError}</p>
                            )}
                            {!loadingLibrary && !libraryError && serverFiles.length === 0 && (
                                <p className="p-4 text-sm text-zinc-500">
                                    Nothing here yet. Copy a video into {serverRoots.join(' or ') || 'the server media directory'} and refresh.
                                </p>
                            )}
                            {serverFiles.map((f) => (
                                <button
                                    key={f.path}
                                    type="button"
                                    onClick={() => setServerPath(f.path)}
                                    className={`w-full text-left px-3 py-2 flex items-center gap-3 transition-colors ${serverPath === f.path ? 'bg-primary/10' : 'hover:bg-white/5'
                                        }`}
                                >
                                    <FileVideo size={16} className={serverPath === f.path ? 'text-primary shrink-0' : 'text-zinc-500 shrink-0'} />
                                    <span className="flex-1 min-w-0">
                                        <span className="block text-sm text-white truncate">{f.name}</span>
                                        <span className="block text-xs text-zinc-500 truncate">{f.rel_path}</span>
                                    </span>
                                    <span className="text-xs text-zinc-500 shrink-0">{prettySize(Math.round(f.size_mb))}</span>
                                </button>
                            ))}
                        </div>

                        <div>
                            <p className="text-xs text-zinc-500 mb-1">…or paste a path on the server</p>
                            <input
                                type="text"
                                value={serverPath}
                                onChange={(e) => setServerPath(e.target.value)}
                                placeholder="/app/media/garage-build-2h.mp4"
                                className="input-field"
                                spellCheck={false}
                            />
                        </div>
                    </div>
                )}

                <label className="flex items-start gap-2 mt-5 text-xs text-zinc-400 cursor-pointer select-none">
                    <input
                        type="checkbox"
                        checked={acknowledged}
                        onChange={(e) => setAcknowledged(e.target.checked)}
                        className="mt-0.5 accent-primary cursor-pointer"
                    />
                    <span>
                        I confirm I own this content or have the rights to process it. I am responsible for any content I submit. See our <a href="/#legal" target="_blank" rel="noopener noreferrer" className="text-primary underline" onClick={(e) => e.stopPropagation()}>Terms & Privacy</a>.
                    </span>
                </label>

                <button
                    type="submit"
                    disabled={
                        isProcessing || !acknowledged
                        || (mode === 'url' && !url)
                        || (mode === 'file' && !file)
                        || (mode === 'server' && !serverPath.trim())
                    }
                    className="w-full btn-primary mt-4 flex items-center justify-center gap-2"
                >
                    {isProcessing ? (
                        <>
                            <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                            Processing Video...
                        </>
                    ) : wantsPlanner ? (
                        <>
                            <Eye size={18} />
                            Preview Parts
                        </>
                    ) : (
                        <>
                            Generate Clips
                        </>
                    )}
                </button>
            </form>
        </div>
    );
}
