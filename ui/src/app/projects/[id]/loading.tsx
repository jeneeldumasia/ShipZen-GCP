export default function Loading() {
  return (
    <div className="space-y-6 animate-pulse">
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <div className="h-8 w-64 bg-zinc-800 rounded"></div>
          <div className="h-4 w-32 bg-zinc-800/50 rounded"></div>
        </div>
        <div className="h-10 w-40 bg-zinc-800 rounded"></div>
      </div>
      <div className="flex gap-4 border-b border-zinc-800 pb-2">
        <div className="h-8 w-24 bg-zinc-800 rounded"></div>
        <div className="h-8 w-24 bg-zinc-800 rounded"></div>
      </div>
      <div className="space-y-4 mt-6">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-16 bg-zinc-800/50 rounded-xl border border-zinc-800"></div>
        ))}
      </div>
    </div>
  );
}
