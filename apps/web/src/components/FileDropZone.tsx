'use client';

import { useCallback, useRef, useState } from 'react';

interface Props {
  onFile: (file: File) => void;
}

export function FileDropZone({ onFile }: Props) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file && (file.name.endsWith('.json') || file.type === 'application/json')) {
        onFile(file);
      }
    },
    [onFile]
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) onFile(file);
    },
    [onFile]
  );

  return (
    <div className="flex-1 flex items-center justify-center h-full p-8">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`
          w-full max-w-lg flex flex-col items-center justify-center gap-4 py-20
          border-2 border-dashed rounded-2xl cursor-pointer transition-all duration-200
          ${
            dragOver
              ? 'border-blue-400 bg-blue-900/20 scale-105'
              : 'border-gray-600 hover:border-gray-400 hover:bg-gray-800/50'
          }
        `}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".json,application/json"
          className="hidden"
          onChange={handleChange}
        />
        <div className="text-6xl select-none">📂</div>
        <div className="text-center">
          <p className="text-gray-200 font-medium text-lg">
            {dragOver ? 'Drop it!' : 'Drop your signature JSON here'}
          </p>
          <p className="text-gray-500 text-sm mt-1">or click to browse</p>
        </div>
        <span className="text-xs text-gray-600 bg-gray-800 px-3 py-1 rounded-full border border-gray-700">
          ImmPort study signature .json
        </span>
      </div>
    </div>
  );
}
