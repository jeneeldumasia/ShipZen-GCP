"use client";

import { useEffect, useState } from "react";
import { Activity } from "lucide-react";
import { api, MetricsResponse } from "@/lib/api";

type Range = "1h" | "6h" | "24h";
type Point = [number, number | null];

const CHARTS: { key: string; title: string; format: (v: number) => string }[] = [
  { key: "requests_per_s", title: "Requests / min", format: v => (v * 60).toFixed(v * 60 < 10 ? 1 : 0) },
  { key: "errors_per_s", title: "Errors (5xx) / min", format: v => (v * 60).toFixed(v * 60 < 10 ? 1 : 0) },
  { key: "p95_ms", title: "Response time p95", format: v => `${v < 10 ? v.toFixed(1) : Math.round(v)} ms` },
  { key: "cpu_cores", title: "CPU", format: v => `${Math.round(v * 1000)} m` },
  { key: "memory_bytes", title: "Memory", format: v => `${Math.round(v / 1048576)} MiB` },
  { key: "instances", title: "Instances", format: v => `${Math.round(v)}` },
];

function Sparkline({ points }: { points: Point[] }) {
  const W = 240, H = 56;
  const vals = points.filter((p): p is [number, number] => p[1] != null);
  if (vals.length < 2) return <div className="h-14 flex items-center text-xs text-text-secondary">No data yet</div>;
  const t0 = vals[0][0], t1 = vals[vals.length - 1][0];
  const max = Math.max(...vals.map(p => p[1]), 1e-9);
  const x = (t: number) => ((t - t0) / Math.max(t1 - t0, 1)) * W;
  const y = (v: number) => H - 2 - (v / max) * (H - 4);
  const d = vals.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-14" preserveAspectRatio="none" aria-hidden>
      <path d={`${d} L${W},${H} L0,${H} Z`} className="fill-brand" opacity={0.12} />
      <path d={d} className="stroke-brand" fill="none" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/** Traffic, errors, latency and resource use of the project's app, from Prometheus. */
export function AppMetrics({ projectId }: { projectId: string }) {
  const [range, setRange] = useState<Range>("1h");
  const [data, setData] = useState<MetricsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api.projects.metrics(projectId, range)
        .then(d => { if (!cancelled) { setData(d); setError(null); } })
        .catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : "Metrics are unavailable"); });
    load();
    const t = setInterval(load, 60_000);
    return () => { cancelled = true; clearInterval(t); };
  }, [projectId, range]);

  return (
    <section className="max-w-5xl mx-auto mt-16">
      <div className="flex items-center justify-between mb-3">
        <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-widest text-text-primary">
          <Activity size={16} /> Metrics
        </h2>
        <div className="flex gap-1">
          {(["1h", "6h", "24h"] as Range[]).map(r => (
            <button key={r} onClick={() => setRange(r)}
              className={`px-2 py-1 text-xs rounded ${r === range ? "bg-brand text-white" : "text-text-secondary hover:text-text-primary"}`}>
              {r}
            </button>
          ))}
        </div>
      </div>
      {error && <p className="text-sm text-amber-500 mb-3">{error}</p>}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {CHARTS.map(c => {
          const pts = (data?.series[c.key] ?? []) as Point[];
          const latest = [...pts].reverse().find(p => p[1] != null)?.[1];
          return (
            <div key={c.key} className="border border-canvas-border rounded p-3">
              <div className="flex items-baseline justify-between mb-1">
                <span className="text-xs text-text-secondary">{c.title}</span>
                <span className="text-sm font-mono text-text-primary">{latest != null ? c.format(latest) : "–"}</span>
              </div>
              <Sparkline points={pts} />
            </div>
          );
        })}
      </div>
    </section>
  );
}
