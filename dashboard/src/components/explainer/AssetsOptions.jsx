import React from 'react';

// Toggles for the assets stage (maps 1:1 to service.AssetOpts / POST /assets).
const TOGGLES = [
  { key: 'no_clips', label: 'No accent clips' },
  { key: 'no_visuals', label: 'No b-roll / aids' },
  { key: 'ai_visuals', label: 'AI stills (vs stock)' },
  { key: 'no_svg', label: 'No SVG graphics' },
  { key: 'no_music', label: 'No music bed' },
];

export default function AssetsOptions({ opts, setOpts }) {
  const set = (k, v) => setOpts({ ...opts, [k]: v });
  return (
    <div className="mt-3 p-3 rounded-lg bg-black/20 space-y-3">
      <div className="grid grid-cols-2 gap-2">
        {TOGGLES.map((t) => (
          <label key={t.key} className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer">
            <input
              type="checkbox"
              checked={!!opts[t.key]}
              onChange={(e) => set(t.key, e.target.checked)}
              className="accent-cyan-500"
            />
            {t.label}
          </label>
        ))}
      </div>
      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2 text-xs text-zinc-400">
          Voice
          <input
            type="text"
            placeholder="brand default"
            value={opts.voice || ''}
            onChange={(e) => set('voice', e.target.value)}
            className="input-field !py-1 !px-2 !text-xs w-28"
          />
        </label>
        <label className="flex items-center gap-2 text-xs text-zinc-400">
          Speed
          <input
            type="number" step="0.05" min="0.5" max="2"
            value={opts.speed ?? 1.0}
            onChange={(e) => set('speed', parseFloat(e.target.value) || 1.0)}
            className="input-field !py-1 !px-2 !text-xs w-16"
          />
        </label>
      </div>
    </div>
  );
}
