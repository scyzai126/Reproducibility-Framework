'use client';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html>
      <body>
        <div className="flex h-screen items-center justify-center flex-col gap-4">
          <p className="text-red-500 text-sm">{error.message || 'Something went wrong.'}</p>
          <button onClick={reset} className="px-4 py-2 rounded-lg bg-emerald-600 text-white text-sm">
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
