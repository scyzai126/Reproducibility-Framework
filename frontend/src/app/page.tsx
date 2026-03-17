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
  const [sidebarOpen, setSidebarOpen] = useState(true);
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

    try {
      const result = await runAgentText(text);

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

  const handleFileUpload = async (file: File) => {
    const userMsgId = crypto.randomUUID();
    const assistantMsgId = crypto.randomUUID();

    // For pasted JSON (virtual file named input.json), store text as content
    const isPasted = file.name === 'input.json';
    const pastedText = isPasted ? await file.text() : '';

    const userMsg: ChatMessage = {
      id: userMsgId,
      role: 'user',
      content: pastedText,
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

    try {
      const result = await runAgentUpload(file);

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
      <Sidebar
        sessions={sessions}
        currentId={currentSessionId}
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen((v) => !v)}
        onNewChat={handleNewChat}
        onSelectSession={handleSelectSession}
      />

      <main className="flex-1 flex flex-col min-w-0">
        {messages.length === 0 ? (
          /* Welcome screen */
          <div className="flex-1 flex flex-col items-center justify-center px-4">
            <div className="w-14 h-14 rounded-full bg-emerald-600 flex items-center justify-center text-white text-xl font-bold mb-5">
              AI
            </div>
            <h1 className="text-3xl font-semibold text-gray-800 mb-2">ImmTrace</h1>
            <p className="text-gray-500 text-base mb-8">
              Upload an ImmPort signature JSON file, or ask a question in plain text
            </p>

            {/* Example questions */}
            <div className="w-full max-w-2xl mb-6">
              <p className="text-xs text-gray-400 uppercase tracking-wide mb-3">Example questions</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {[
                  'In SDY1669, find all healthy subjects with plasma samples analyzed by Olink',
                  'In SDY1669, find COVID-19 subjects with PBMC samples analyzed by CITE-seq',
                  'In SDY1669, find all female subjects',
                  'In SDY1669, find healthy female subjects with plasma samples',
                  'In SDY1669, find COVID-19 subjects from the Atlanta cohort',
                  'In SDY1669, find all subjects with PBMC samples analyzed by CITE-seq',
                ].map((q) => (
                  <button
                    key={q}
                    onClick={() => handleTextMessage(q)}
                    disabled={isAnalyzing}
                    className="text-left px-4 py-3 rounded-xl border border-gray-200 text-sm text-gray-600 hover:border-emerald-400 hover:text-emerald-700 hover:bg-emerald-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>

            <div className="w-full max-w-2xl">
              <ChatInput onFileUpload={handleFileUpload} onTextSubmit={handleTextMessage} disabled={isAnalyzing} />
              <p className="text-center text-xs text-gray-400 mt-3">
                Accepts .json signature files · drag &amp; drop supported
              </p>
            </div>
          </div>
        ) : (
          <>
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
                <ChatInput onFileUpload={handleFileUpload} onTextSubmit={handleTextMessage} disabled={isAnalyzing} />
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
