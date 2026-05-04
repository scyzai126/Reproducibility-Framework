'use client';

import { useRef, useState, useEffect } from 'react';

interface Props {
  onTextSubmit: (text: string) => void;
  disabled?: boolean;
  prefill?: string;
}

export default function ChatInput({ onTextSubmit, disabled, prefill }: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
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

  const canSend = !disabled && text.trim().length > 0;

  const handleSend = () => {
    if (!canSend) return;
    onTextSubmit(text.trim());
    setText('');
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="bg-white rounded-2xl border border-gray-300 shadow-sm overflow-hidden">
      <div className="flex items-end gap-2 p-3">
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
              : 'Enter a paper URL, PMID, or study accession to get started…'
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
