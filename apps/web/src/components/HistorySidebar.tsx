'use client';

import type { RunRecord } from '@/lib/types';

interface Props {
  history: RunRecord[];
  currentRunId?: string;
  onSelect: (run: RunRecord) => void;
  onNew: () => void;
}

export function HistorySidebar({ history, currentRunId, onSelect }: Props) {
  return (
    <aside className="w-64 flex-shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col">
      <div className="px-4 py-4 border-b border-gray-800">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Run History</p>
      </div>
      <div className="flex-1 overflow-y-auto">
        {history.length === 0 ? (
          <div className="p-6 text-xs text-gray-600 text-center leading-relaxed">
            No runs yet.
            <br />
            Upload a signature JSON to get started.
          </div>
        ) : (
          <ul className="py-1">
            {history.map((run) => (
              <li key={run.id}>
                <button
                  onClick={() => onSelect(run)}
                  className={`w-full text-left px-4 py-3 hover:bg-gray-800 transition-colors ${
                    currentRunId === run.id
                      ? 'bg-gray-800 border-l-2 border-blue-500'
                      : 'border-l-2 border-transparent'
                  }`}
                >
                  <p className="text-sm text-gray-200 truncate">{run.filename}</p>
                  <p className="text-xs text-blue-400 mt-0.5 truncate">
                    {run.study_accession || '—'}
                  </p>
                  <p className="text-xs text-gray-600 mt-0.5">
                    {new Date(run.timestamp).toLocaleString([], {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </p>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}
