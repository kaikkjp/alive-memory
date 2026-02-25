import Link from "next/link";

export default function Home() {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen px-4">
      <h1 className="text-3xl font-light tracking-[0.2em] uppercase mb-2">alive</h1>
      <p className="text-[#9a8c7a] text-sm mb-10">persistent AI characters</p>
      <Link
        href="/login"
        className="px-6 py-2.5 bg-[#d4a574] hover:bg-[#c4955a] text-[#0a0a0a] rounded-lg text-sm font-medium transition-colors"
      >
        Enter
      </Link>
    </div>
  );
}
