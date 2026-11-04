"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Pause, Play, Search, ScrollText } from "lucide-react";
import { api, RuntimeLogLine } from "@/lib/api";

const POLL_MS = 3000;
const KEEP = 2000;

function levelClass(line: string): string {
  if (/\b(error|exception|fatal|panic|traceback)\b/i.test(line)) return "text-red-400";
  if (/\bwarn(ing)?\b/i.test(line)) return "text-amber-300";
  return "text-zinc-200";
}

function time(tsNs: number): string {
  return new Date(tsNs / 1e6).toLocaleTimeString();
}

/** What the running app prints, refreshed every few seconds while "live" is on. */
export function RuntimeLogs({ projectId, deploymentId }: { projectId: string; deploymentId: string }) {
  const [lines, setLines] = useState<RuntimeLogLine[]>([]);
  const [live, setLive] = useState(true);
  const [query, setQuery] = useState("");
  const [applied, setApplied] = useState("");
  const [error, setError] = useState<string | null>(null);
  const last = useRef<number | undefined>(undefined);
  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  const load = useCallback(async (reset: boolean) => {
    try {
      const res = await api.deployments.runtimeLogs(projectId, deploymentId, {
        since: reset ? undefined : last.current,
        q: applied || undefined,
      });
      setError(null);
      if (res.last != null) last.current = res.last;
      setLines(prev => (reset ? res.lines : [...prev, ...res.lines]).slice(-KEEP));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Logs are unavailable");
    }
  }, [projectId, deploymentId, applied]);

  // (Re)load from scratch when the search changes.
  useEffect(() => {
    last.current = undefined;
    load(true);
  }, [load]);

  useEffect(() => {
    if (!live) return;
    const t = setInterval(() => load(false), POLL_MS);
    return () => clearInterval(t);
  }, [live, load]);

  useEffect(() => {
    const el = box.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [lines]);

  return (
    <section className="max-w-5xl mx-auto mt-16">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-widest text-text-primary">
          <ScrollText size={16} /> Logs
        </h2>
        <div className="flex items-center gap-2">
          <form onSubmit={e => { e.preventDefault(); setApplied(query.trim()); }} className="flex items-center gap-1.5 border border-canvas-border rounded px-2 py-1">
            <Search size={14} className="text-text-secondary" />
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Filter lines"
              maxLength={200}
              className="bg-transparent text-xs outline-none w-40 text-text-primary"
            />
          </form>
          <button onClick={() => setLive(v => !v)} className="btn-ghost py-1 text-xs" aria-pressed={live}>
            {live ? <><Pause size={14} /> Live</> : <><Play size={14} /> Paused</>}
          </button>
        </div>
      </div>
      <div
        ref={box}
        onScroll={e => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        }}
        className="h-96 overflow-auto rounded border border-canvas-border bg-zinc-950 p-3 font-mono text-xs leading-relaxed"
      >
        {error && <div className="text-amber-300">{error}</div>}
        {!error && lines.length === 0 && (
          <div className="text-zinc-500">
            {applied ? "No lines match in the last hour." : "Nothing logged in the last hour. Anything your app prints to stdout or stderr shows up here."}
          </div>
        )}
        {lines.map((l, i) => (
          <div key={`${l.ts}-${i}`} className="flex gap-3 whitespace-pre-wrap break-all">
            <span className="text-zinc-500 shrink-0">{time(l.ts)}</span>
            <span className={levelClass(l.line)}>{l.line}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
