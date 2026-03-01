"use client";

export default function GlobalError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-[#0a0a0f] text-[#e5e5e5] min-h-screen flex items-center justify-center">
        <div className="text-center space-y-4">
          <h1 className="text-lg font-medium">Something went wrong</h1>
          <button
            onClick={reset}
            className="px-4 py-2 bg-[#262626] hover:bg-[#333] rounded-md text-sm transition-colors"
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
