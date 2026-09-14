'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ChatSession } from '@/lib/types';

interface Props {
  sessions: ChatSession[];
  currentId: string | null;
  isOpen: boolean;
  onToggle: () => void;
  onNewChat: () => void;
  onSelectSession: (id: string) => void;
  cachedPmids: string[];
  onSelectPaper: (pmid: string) => void;
}

export default function Sidebar({ sessions, currentId, isOpen, onToggle, onNewChat, onSelectSession, cachedPmids, onSelectPaper }: Props) {
  // Collapsed by default: the list is 16 PMIDs and pushes the rest of the sidebar off-screen.
  const [papersExpanded, setPapersExpanded] = useState(false);
  const [historyExpanded, setHistoryExpanded] = useState(true);
  const formatDate = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  // Collapsed: just a narrow strip with the toggle button
  if (!isOpen) {
    return (
      <aside className="w-10 flex-shrink-0 bg-gray-50 border-r border-gray-200 flex flex-col items-center pt-3 h-full">
        <button
          onClick={onToggle}
          className="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-200 transition-colors"
          title="Open sidebar"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>
      </aside>
    );
  }

  return (
    <aside className="w-64 flex-shrink-0 bg-gray-50 border-r border-gray-200 flex flex-col h-full">
      <div className="p-3 border-b border-gray-200 flex items-center gap-2">
        <button
          onClick={onToggle}
          className="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-200 transition-colors flex-shrink-0"
          title="Close sidebar"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>
        <button
          onClick={onNewChat}
          className="flex-1 flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-gray-200 text-gray-600 hover:text-gray-900 transition-colors text-sm font-medium"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          New analysis
        </button>
      </div>

      {/* Scrollable body containing both sections */}
      <div className="flex-1 overflow-y-auto min-h-0">

        {/* Cached papers section */}
        <div className="border-b border-gray-200">
          <button
            onClick={() => setPapersExpanded((v) => !v)}
            className="w-full flex items-center justify-between px-3 py-2.5 text-xs font-medium text-gray-500 hover:bg-gray-100 transition-colors"
          >
            <span className="flex items-center gap-1.5">
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>
              </svg>
              Paper Library ({cachedPmids.length})
            </span>
            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
              className={`transition-transform ${papersExpanded ? 'rotate-180' : ''}`}>
              <polyline points="6 9 12 15 18 9"/>
            </svg>
          </button>
          {papersExpanded && (
            <div className="px-2 pb-2 space-y-0.5">
              {cachedPmids.map((pmid) => (
                <button
                  key={pmid}
                  onClick={() => onSelectPaper(pmid)}
                  className="w-full text-left px-3 py-1.5 rounded-lg text-xs font-mono text-gray-600 hover:bg-emerald-50 hover:text-emerald-800 transition-colors"
                >
                  PMID:{pmid}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Assays — the corpus table, and building one paper's registry. Not a chat session. */}
        <div className="border-b border-gray-200">
          <Link
            href="/assays"
            className="w-full flex items-center gap-1.5 px-3 py-2.5 text-xs font-medium text-gray-500 hover:bg-gray-100 hover:text-emerald-800 transition-colors"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 3h18v4H3z"/><path d="M3 11h18v4H3z"/><path d="M3 19h18v2H3z"/>
            </svg>
            Assays
          </Link>
        </div>

        {/* Chat history section */}
        <div>
          <button
            onClick={() => setHistoryExpanded((v) => !v)}
            className="w-full flex items-center justify-between px-3 py-2.5 text-xs font-medium text-gray-500 hover:bg-gray-100 transition-colors"
          >
            <span className="flex items-center gap-1.5">
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
              </svg>
              Chat History
            </span>
            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
              className={`transition-transform ${historyExpanded ? 'rotate-180' : ''}`}>
              <polyline points="6 9 12 15 18 9"/>
            </svg>
          </button>
          {historyExpanded && (
            <div className="px-2 pb-2 space-y-0.5">
              {sessions.length === 0 ? (
                <p className="text-gray-400 text-xs px-3 py-4">No sessions yet</p>
              ) : (
                sessions.map((session) => (
                  <button
                    key={session.id}
                    onClick={() => onSelectSession(session.id)}
                    className={`w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors ${
                      session.id === currentId
                        ? 'bg-gray-200 text-gray-900'
                        : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                    }`}
                  >
                    <div className="truncate font-medium text-gray-800">{session.title}</div>
                    <div className="text-xs text-gray-400 mt-0.5">{formatDate(session.createdAt)}</div>
                  </button>
                ))
              )}
            </div>
          )}
        </div>

      </div>

      <div className="p-3 border-t border-gray-200">
        <p className="text-xs text-gray-400 text-center">An AI-powered reproducibility framework for systems immunology</p>
      </div>
    </aside>
  );
}
