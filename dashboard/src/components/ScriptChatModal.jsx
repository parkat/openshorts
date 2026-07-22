import React, { useState, useEffect, useRef } from 'react';
import { X, Send, Loader2, Copy, Check, Sparkles, MessageSquare } from 'lucide-react';
import { getApiUrl } from '../config';

const QUICK_ACTIONS = [
    { label: '10 Titles', prompt: 'Give me 10 viral, scroll-stopping title options for this short. Keep each under 70 characters.' },
    { label: 'Description', prompt: 'Write an engaging caption/description for this short (2-3 sentences) ending with a call to action.' },
    { label: 'Hashtags', prompt: 'Give me 15-20 relevant, high-reach hashtags for this short as a single copy-paste block.' },
    { label: 'Hook ideas', prompt: 'Suggest 5 strong opening hook lines (for the first 2 seconds) for this short.' },
];

function CopyButton({ text }) {
    const [copied, setCopied] = useState(false);
    return (
        <button
            onClick={() => {
                navigator.clipboard?.writeText(text).then(() => {
                    setCopied(true);
                    setTimeout(() => setCopied(false), 1500);
                });
            }}
            className="text-zinc-500 hover:text-white transition-colors shrink-0"
            title="Copy"
        >
            {copied ? <Check size={14} className="text-green-400" /> : <Copy size={14} />}
        </button>
    );
}

export default function ScriptChatModal({ isOpen, onClose, jobId, clipIndex, geminiApiKey, clipTitle }) {
    const [scriptText, setScriptText] = useState('');
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const scrollRef = useRef(null);

    // Load the clip script for display when the modal opens.
    useEffect(() => {
        if (!isOpen || !jobId || clipIndex === undefined || clipIndex === null) return;
        setScriptText('');
        fetch(getApiUrl(`/api/clip/${jobId}/${clipIndex}/transcript`))
            .then((r) => (r.ok ? r.json() : null))
            .then((d) => {
                if (d && Array.isArray(d.captions)) {
                    setScriptText(d.captions.map((c) => c.text).join(' ').trim());
                }
            })
            .catch(() => {});
    }, [isOpen, jobId, clipIndex]);

    // Auto-scroll to the latest message.
    useEffect(() => {
        if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }, [messages, loading]);

    if (!isOpen) return null;

    const send = async (text) => {
        const msg = (text || '').trim();
        if (!msg || loading) return;
        if (!geminiApiKey) {
            setError('Set your Gemini API key in Settings first.');
            return;
        }
        const history = messages;
        setMessages((prev) => [...prev, { role: 'user', content: msg }]);
        setInput('');
        setLoading(true);
        setError(null);
        try {
            const res = await fetch(getApiUrl(`/api/clip/${jobId}/${clipIndex}/chat`), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Gemini-Key': geminiApiKey },
                body: JSON.stringify({ message: msg, history }),
            });
            if (!res.ok) {
                const body = await res.json().catch(() => ({}));
                throw new Error(body.detail || `Request failed (${res.status})`);
            }
            const data = await res.json();
            if (data.script && !scriptText) setScriptText(data.script);
            setMessages((prev) => [...prev, { role: 'assistant', content: data.reply || '(empty response)' }]);
        } catch (e) {
            setError(e.message || 'Something went wrong');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-[fadeIn_0.2s_ease-out]">
            <div className="bg-[#121214] border border-white/10 rounded-2xl w-full max-w-2xl shadow-2xl relative flex flex-col max-h-[90vh]">
                {/* Header */}
                <div className="flex items-start justify-between p-5 border-b border-white/5">
                    <div className="flex items-center gap-3">
                        <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-fuchsia-600 to-indigo-600 flex items-center justify-center shrink-0">
                            <MessageSquare size={18} className="text-white" />
                        </div>
                        <div>
                            <h3 className="text-white font-bold text-base leading-tight">AI Copy Assistant</h3>
                            <p className="text-zinc-400 text-xs mt-0.5">
                                Chat with Gemini using this clip&apos;s script — titles, descriptions, hashtags &amp; more
                            </p>
                        </div>
                    </div>
                    <button onClick={onClose} className="text-zinc-500 hover:text-white shrink-0">
                        <X size={20} />
                    </button>
                </div>

                {/* Script preview */}
                <div className="px-5 pt-4">
                    <div className="text-[11px] uppercase tracking-wide text-zinc-500 mb-1 flex items-center justify-between">
                        <span>Clip script{clipTitle ? ` · ${clipTitle}` : ''}</span>
                        {scriptText && <CopyButton text={scriptText} />}
                    </div>
                    <div className="text-xs text-zinc-300 bg-black/40 border border-white/5 rounded-lg p-3 max-h-24 overflow-y-auto custom-scrollbar whitespace-pre-wrap">
                        {scriptText || <span className="text-zinc-500 italic">Loading clip script…</span>}
                    </div>
                </div>

                {/* Quick actions */}
                <div className="px-5 pt-3 flex flex-wrap gap-2">
                    {QUICK_ACTIONS.map((qa) => (
                        <button
                            key={qa.label}
                            onClick={() => send(qa.prompt)}
                            disabled={loading}
                            className="text-xs px-3 py-1.5 rounded-full bg-white/5 hover:bg-white/10 border border-white/10 text-zinc-200 disabled:opacity-50 transition-colors flex items-center gap-1.5"
                        >
                            <Sparkles size={12} className="text-fuchsia-400" /> {qa.label}
                        </button>
                    ))}
                </div>

                {/* Messages */}
                <div ref={scrollRef} className="flex-1 overflow-y-auto custom-scrollbar px-5 py-4 space-y-3 min-h-[160px]">
                    {messages.length === 0 && !loading && (
                        <div className="text-center text-zinc-500 text-sm py-8">
                            Tap a quick action above, or ask anything about this clip.
                        </div>
                    )}
                    {messages.map((m, i) => (
                        <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                            <div
                                className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm ${
                                    m.role === 'user'
                                        ? 'bg-indigo-600 text-white rounded-br-sm'
                                        : 'bg-white/5 border border-white/10 text-zinc-100 rounded-bl-sm'
                                }`}
                            >
                                <div className="whitespace-pre-wrap leading-relaxed">{m.content}</div>
                                {m.role === 'assistant' && (
                                    <div className="mt-2 flex justify-end">
                                        <CopyButton text={m.content} />
                                    </div>
                                )}
                            </div>
                        </div>
                    ))}
                    {loading && (
                        <div className="flex justify-start">
                            <div className="bg-white/5 border border-white/10 text-zinc-400 rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm flex items-center gap-2">
                                <Loader2 size={14} className="animate-spin" /> Thinking…
                            </div>
                        </div>
                    )}
                </div>

                {error && (
                    <div className="px-5 pb-2 text-xs text-red-400">{error}</div>
                )}

                {/* Input */}
                <div className="p-4 border-t border-white/5 flex items-end gap-2">
                    <textarea
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey) {
                                e.preventDefault();
                                send(input);
                            }
                        }}
                        rows={1}
                        placeholder="Ask for titles, a caption, hashtags…"
                        className="flex-1 resize-none bg-black/40 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-indigo-500 max-h-32"
                    />
                    <button
                        onClick={() => send(input)}
                        disabled={loading || !input.trim()}
                        className="shrink-0 w-10 h-10 rounded-xl bg-gradient-to-br from-fuchsia-600 to-indigo-600 hover:from-fuchsia-500 hover:to-indigo-500 disabled:opacity-40 text-white flex items-center justify-center transition-all active:scale-95"
                    >
                        {loading ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                    </button>
                </div>
            </div>
        </div>
    );
}
