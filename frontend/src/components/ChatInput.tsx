'use client';

import { useRef, useState, useEffect } from 'react';

interface Props {
  onFileUpload: (file: File, question?: string) => void;
  onTextSubmit: (text: string) => void;
  disabled?: boolean;
  prefill?: string;
}

function isJson(s: string): boolean {
  try { JSON.parse(s); return true; } catch { return false; }
}

export default function ChatInput({ onFileUpload, onTextSubmit, disabled, prefill }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [text, setText] = useState('');

  useEffect(() => {
    if (prefill) setText(prefill);
  }, [prefill]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  }, [text]);

  const canSend = !disabled && (!!selectedFile || text.trim().length > 0);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setSelectedFile(file);
      setText('');
    }
  };

  const handleSend = () => {
    if (!canSend) return;

    if (selectedFile) {
      onFileUpload(selectedFile, text.trim() || undefined);
      setSelectedFile(null);
      setText('');
      if (fileRef.current) fileRef.current.value = '';
    } else if (text.trim()) {
      if (isJson(text.trim())) {
        // Pasted JSON → wrap as virtual file and use the upload endpoint
        const blob = new Blob([text.trim()], { type: 'application/json' });
        onFileUpload(new File([blob], 'input.json', { type: 'application/json' }));
      } else {
        // Plain natural language → use the text endpoint
        onTextSubmit(text.trim());
      }
      setText('');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (file && (file.name.endsWith('.json') || file.name.endsWith('.pdf') || file.name.endsWith('.txt'))) {
      setSelectedFile(file);
      setText('');
    }
  };

  const handleDragOver = (e: React.DragEvent) => e.preventDefault();

  return (
    <div
      className="bg-white rounded-2xl border border-gray-300 shadow-sm overflow-hidden"
      onDrop={handleDrop}
      onDragOver={handleDragOver}
    >
      {/* Attached file chip */}
      {selectedFile && (
        <div className="flex items-center gap-2 px-3 pt-3">
          <div className="flex items-center gap-2 bg-gray-100 rounded-lg px-3 py-1.5 text-sm">
            <span className="text-blue-500">📄</span>
            <span className="text-gray-700 truncate max-w-xs">{selectedFile.name}</span>
            <button
              onClick={() => {
                setSelectedFile(null);
                if (fileRef.current) fileRef.current.value = '';
              }}
              className="text-gray-400 hover:text-gray-700 ml-1 leading-none"
            >
              ×
            </button>
          </div>
        </div>
      )}

      {/* Text area */}
      <div className="flex items-end gap-2 p-3">
        <input
          type="file"
          ref={fileRef}
          accept=".json,.pdf,.txt"
          className="hidden"
          onChange={handleFileChange}
        />

        <button
          onClick={() => fileRef.current?.click()}
          disabled={disabled}
          className="p-2 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex-shrink-0"
          title="Upload PDF or JSON file"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
          </svg>
        </button>

        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          rows={1}
          placeholder={
            disabled
              ? 'Analyzing…'
              : selectedFile
              ? 'Optional: ask a question about this paper…'
              : 'Upload a paper with the 📎 button, or ask a question…'
          }
          className="flex-1 bg-transparent outline-none text-gray-800 placeholder-gray-400 text-sm resize-none overflow-hidden leading-6 disabled:cursor-default"
          style={{ minHeight: '24px', maxHeight: '200px' }}
        />

        <button
          onClick={handleSend}
          disabled={!canSend}
          className={`p-2 rounded-lg transition-colors flex-shrink-0 ${
            canSend
              ? 'bg-gray-900 text-white hover:bg-gray-700'
              : 'bg-gray-200 text-gray-400 cursor-not-allowed'
          }`}
          title="Send"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="19" x2="12" y2="5" />
            <polyline points="5 12 12 5 19 12" />
          </svg>
        </button>
      </div>
    </div>
  );
}
