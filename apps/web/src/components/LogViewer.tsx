interface Props {
  content: string;
}

export function LogViewer({ content }: Props) {
  return (
    <div className="max-h-72 overflow-y-auto bg-gray-950">
      <pre className="px-6 py-4 text-xs text-gray-400 font-mono whitespace-pre-wrap leading-relaxed">
        {content || 'No log content available.'}
      </pre>
    </div>
  );
}
