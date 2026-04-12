'use client';

import { useEffect, useRef, useState } from 'react';
import Sidebar from '@/components/Sidebar';
import ChatMessageComponent from '@/components/ChatMessage';
import ChatInput from '@/components/ChatInput';
import { runAgentUpload, runAgentText } from '@/lib/api';
import type { ChatMessage, ChatSession } from '@/lib/types';

const STORAGE_KEY = 'chat_sessions';
const MAX_SESSIONS = 20;

export default function Home() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  // Stores the last unanswered question when the backend asks for clarification,
  // so it can be prepended to the user's follow-up reply.
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);

  // Default sidebar open only on wider screens (after hydration)
  useEffect(() => {
    setSidebarOpen(window.innerWidth >= 768);
  }, []);
  const [prefillText, setPrefillText] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) setSessions(JSON.parse(saved));
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const persistSessions = (updated: ChatSession[]) => {
    const trimmed = updated.slice(0, MAX_SESSIONS);
    setSessions(trimmed);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
  };

  const handleNewChat = () => {
    setMessages([]);
    setCurrentSessionId(null);
  };

  const handleSelectSession = (id: string) => {
    const session = sessions.find((s) => s.id === id);
    if (session) {
      setMessages(session.messages);
      setCurrentSessionId(id);
    }
  };

  const handleTextMessage = async (text: string) => {
    // If backend previously asked a clarifying question, prepend the original
    // question so the backend has full context on the follow-up.
    const fullText = pendingQuestion ? `${pendingQuestion} ${text}` : text;
    setPendingQuestion(null);

    const userMsgId = crypto.randomUUID();
    const assistantMsgId = crypto.randomUUID();

    const userMsg: ChatMessage = {
      id: userMsgId,
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
    };

    const loadingMsg: ChatMessage = {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
      isLoading: true,
    };

    const withLoading = [...messages, userMsg, loadingMsg];
    setMessages(withLoading);
    setIsAnalyzing(true);
    setPrefillText('');

    try {
      const result = await runAgentText(fullText);

      if (result.type === 'clarification') {
        // Store the combined text so the next reply has full context
        setPendingQuestion(fullText);
      }

      const finalMessages = withLoading.map((m) =>
        m.id === assistantMsgId ? { ...m, isLoading: false, result } : m
      );
      setMessages(finalMessages);

      const sessionTitle = text.slice(0, 40) + (text.length > 40 ? '…' : '');
      let updatedSessions: ChatSession[];

      if (currentSessionId) {
        updatedSessions = sessions.map((s) =>
          s.id === currentSessionId ? { ...s, messages: finalMessages } : s
        );
      } else {
        const newId = crypto.randomUUID();
        updatedSessions = [
          { id: newId, title: sessionTitle, messages: finalMessages, createdAt: new Date().toISOString() },
          ...sessions,
        ];
        setCurrentSessionId(newId);
      }

      persistSessions(updatedSessions);
    } catch (err) {
      const errorMessages = withLoading.map((m) =>
        m.id === assistantMsgId
          ? { ...m, isLoading: false, error: err instanceof Error ? err.message : String(err) }
          : m
      );
      setMessages(errorMessages);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleFileUpload = async (file: File, question?: string) => {
    const userMsgId = crypto.randomUUID();
    const assistantMsgId = crypto.randomUUID();

    // For pasted JSON (virtual file named input.json), store text as content
    const isPasted = file.name === 'input.json';
    const pastedText = isPasted ? await file.text() : '';

    const userMsg: ChatMessage = {
      id: userMsgId,
      role: 'user',
      content: question || pastedText,
      filename: file.name,
      timestamp: new Date().toISOString(),
    };

    const loadingMsg: ChatMessage = {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
      isLoading: true,
    };

    const withLoading = [...messages, userMsg, loadingMsg];
    setMessages(withLoading);
    setIsAnalyzing(true);
    setPrefillText('');

    try {
      const [result] = await Promise.all([
        runAgentUpload(file, question),
        new Promise((r) => setTimeout(r, 8000)),
      ]);

      const finalMessages = withLoading.map((m) =>
        m.id === assistantMsgId ? { ...m, isLoading: false, result } : m
      );
      setMessages(finalMessages);

      const sessionTitle = file.name.replace(/\.json$/i, '');
      let updatedSessions: ChatSession[];

      if (currentSessionId) {
        updatedSessions = sessions.map((s) =>
          s.id === currentSessionId ? { ...s, messages: finalMessages } : s
        );
      } else {
        const newId = crypto.randomUUID();
        const newSession: ChatSession = {
          id: newId,
          title: sessionTitle,
          messages: finalMessages,
          createdAt: new Date().toISOString(),
        };
        updatedSessions = [newSession, ...sessions];
        setCurrentSessionId(newId);
      }

      persistSessions(updatedSessions);
    } catch (err) {
      const errorMessages = withLoading.map((m) =>
        m.id === assistantMsgId
          ? {
              ...m,
              isLoading: false,
              error: err instanceof Error ? err.message : String(err),
            }
          : m
      );
      setMessages(errorMessages);
    } finally {
      setIsAnalyzing(false);
    }
  };

  return (
    <div className="flex h-screen bg-white text-gray-900 overflow-hidden">
      {/* Mobile overlay — closes sidebar when tapping outside */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/30 z-10 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar: always in flow on md+, overlay on mobile */}
      <div className={`${sidebarOpen ? 'fixed md:relative z-20 h-full' : 'hidden md:block md:h-full'}`}>
        <Sidebar
          sessions={sessions}
          currentId={currentSessionId}
          isOpen={sidebarOpen}
          onToggle={() => setSidebarOpen((v) => !v)}
          onNewChat={() => { handleNewChat(); setSidebarOpen(false); }}
          onSelectSession={(id) => { handleSelectSession(id); if (window.innerWidth < 768) setSidebarOpen(false); }}
        />
      </div>

      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {messages.length === 0 ? (
          /* Welcome screen */
          <div className="flex-1 flex flex-col items-center justify-center px-4 relative">
            {/* Mobile hamburger */}
            <button
              onClick={() => setSidebarOpen(true)}
              className="absolute top-4 left-4 md:hidden p-2 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
              title="Open menu"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="12" x2="21" y2="12" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </svg>
            </button>
            <div className="w-14 h-14 rounded-full bg-emerald-600 flex items-center justify-center text-white text-xl font-bold mb-5">
              AI
            </div>
            <h1 className="text-3xl font-semibold text-gray-800 mb-2">ClaimRepro</h1>
            <p className="text-gray-500 text-base mb-8">
              Ask questions about a study you're interested in
            </p>

            {/* Example questions */}
            <div className="w-full max-w-2xl mb-6">
              <p className="text-xs text-gray-400 uppercase tracking-wide mb-3">Example questions</p>
              <div className="grid grid-cols-1 gap-2">
                {[
                  'Identify all claims in https://pmc.ncbi.nlm.nih.gov/articles/PMC8761119 and the corresponding subjects for each claim.',
                  'In paper PMID:32788292, identify all healthy subjects whose plasma samples were analyzed using Olink proteomics.',
                ].map((q) => (
                  <button
                    key={q}
                    onClick={() => setPrefillText(q)}
                    disabled={isAnalyzing}
                    className="text-left px-4 py-3 rounded-xl border border-gray-200 text-sm text-gray-600 hover:border-emerald-400 hover:text-emerald-700 hover:bg-emerald-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed select-text break-words whitespace-normal"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>

            <div className="w-full max-w-2xl">
              <ChatInput onFileUpload={handleFileUpload} onTextSubmit={handleTextMessage} disabled={isAnalyzing} prefill={prefillText} />
            </div>
          </div>
        ) : (
          <>
            {/* Mobile header bar */}
            <div className="flex-shrink-0 flex items-center px-4 pt-4 md:hidden">
              <button
                onClick={() => setSidebarOpen(true)}
                className="p-2 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
                title="Open menu"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="3" y1="6" x2="21" y2="6" />
                  <line x1="3" y1="12" x2="21" y2="12" />
                  <line x1="3" y1="18" x2="21" y2="18" />
                </svg>
              </button>
            </div>

            {/* Chat messages */}
            <div className="flex-1 overflow-y-auto">
              <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
                {messages.map((msg) => (
                  <ChatMessageComponent key={msg.id} message={msg} />
                ))}
                <div ref={messagesEndRef} />
              </div>
            </div>

            {/* Input bar */}
            <div className="flex-shrink-0 px-4 pb-6">
              <div className="max-w-3xl mx-auto">
                <ChatInput onFileUpload={handleFileUpload} onTextSubmit={handleTextMessage} disabled={isAnalyzing} prefill={prefillText} />
                <p className="text-center text-xs text-gray-400 mt-2">
                  Upload another file to run a new analysis
                </p>
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
