import Link from "next/link";

export default function Home() {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen px-4">
      <h1 className="text-4xl font-bold mb-2 tracking-tight">alive</h1>
      <p className="text-[#737373] mb-8">persistent AI characters</p>
      <Link
        href="/login"
        className="px-6 py-2.5 bg-[#3b82f6] hover:bg-[#2563eb] rounded-lg text-sm font-medium transition-colors"
      >
        Manager Login
      </Link>
    </div>
  );
}
