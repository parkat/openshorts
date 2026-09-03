import React, { useState } from 'react';
import { FlaskConical, ListVideo, Database, PlusCircle, Calendar } from 'lucide-react';
import ExplainerQueue from './ExplainerQueue';
import ProjectStudio from './ProjectStudio';
import TopicForm from './TopicForm';
import ScheduleView from './ScheduleView';
import CacheExplorer from './CacheExplorer';

// Container for the explainer lane. Owns which sub-view is active and, when in
// the studio, which project. Kept out of App.jsx (already huge); all explainer
// UI lives under components/explainer/.
export default function ExplainerTab() {
  const [view, setView] = useState('queue'); // queue | studio | cache
  const [selectedId, setSelectedId] = useState(null);

  const openStudio = (id) => { setSelectedId(id); setView('studio'); };

  const NavBtn = ({ id, icon: Icon, label }) => (
    <button
      onClick={() => setView(id)}
      className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
        view === id ? 'bg-cyan-500/10 text-cyan-400' : 'text-zinc-400 hover:text-white hover:bg-white/5'
      }`}
    >
      <Icon size={16} />
      <span>{label}</span>
    </button>
  );

  return (
    <div className="h-full flex flex-col animate-[fadeIn_0.3s_ease-out]">
      {/* Header */}
      <div className="px-6 md:px-10 pt-6 pb-4 border-b border-white/5">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-9 h-9 rounded-xl bg-cyan-500/10 text-cyan-400 flex items-center justify-center">
            <FlaskConical size={20} />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white leading-none">Explainer Studio</h1>
            <p className="text-xs text-zinc-500 mt-1">Faceless AI-education Shorts — the full pipeline.</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <NavBtn id="queue" icon={ListVideo} label="Queue" />
          <NavBtn id="topics" icon={PlusCircle} label="Topics" />
          <NavBtn id="schedule" icon={Calendar} label="Schedule" />
          <NavBtn id="cache" icon={Database} label="Cache" />
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        {view === 'queue' && <ExplainerQueue onOpen={openStudio} />}
        {view === 'topics' && <TopicForm onProjectCreated={openStudio} />}
        {view === 'schedule' && <ScheduleView />}
        {view === 'studio' && (
          <ProjectStudio projectId={selectedId} onBack={() => setView('queue')} />
        )}
        {view === 'cache' && <CacheExplorer />}
      </div>
    </div>
  );
}
