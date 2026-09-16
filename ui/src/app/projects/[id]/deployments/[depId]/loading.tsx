export default function Loading() {
  return (
    <div className="space-y-6 animate-pulse">
      <div className="h-4 w-64 bg-zinc-800 rounded"></div>
      
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 space-y-6">
        <div className="flex items-center justify-between">
          <div className="space-y-2">
            <div className="h-6 w-48 bg-zinc-800 rounded"></div>
            <div className="h-4 w-32 bg-zinc-800/50 rounded"></div>
          </div>
          <div className="h-10 w-24 bg-zinc-800 rounded"></div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="space-y-2">
              <div className="h-4 w-16 bg-zinc-800/50 rounded"></div>
              <div className="h-6 w-32 bg-zinc-800 rounded"></div>
            </div>
          ))}
        </div>
      </div>

      <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-zinc-800">
          <div className="h-6 w-32 bg-zinc-800 rounded"></div>
        </div>
        <div className="p-6 space-y-4">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-12 bg-zinc-800/50 rounded-lg border border-zinc-800"></div>
          ))}
        </div>
      </div>
    </div>
  );
}
