"use client";

import { useEffect, useState } from "react";
import { DollarSign } from "lucide-react";
import { api, type SessionCost as Cost } from "@/lib/api";

const usd = (n: number, digits = 2) => `$${n.toFixed(digits)}`;

function hm(hours: number) {
  const total = Math.round(hours * 60);
  return `${Math.floor(total / 60)}h ${String(total % 60).padStart(2, "0")}m`;
}

/** What this cluster session is costing in node time, against the teardown limits. */
export function SessionCost() {
  const [cost, setCost] = useState<Cost | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api.admin
        .cost()
        .then((c) => {
          if (alive) {
            setCost(c);
            setError(null);
          }
        })
        .catch((e) => {
          if (alive) setError(e instanceof Error ? e.message : "Could not load cost");
        });
    load();
    const t = setInterval(load, 60_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const cap = cost?.teardown.hard_cap_hours ?? 12;
  const idle = cost?.teardown.idle_after_hours ?? 9;
  const pct = cost ? Math.min((cost.uptime_hours / cap) * 100, 100) : 0;
  const over = cost ? cost.uptime_hours >= idle : false;

  return (
    <div className="card p-6 animate-fade-in" style={{ animationDuration: "0.45s" }}>
      <div className="flex items-center justify-between mb-6 border-b border-canvas-border pb-4">
        <h2 className="text-lg font-bold text-text-primary flex items-center gap-2">
          <DollarSign size={18} className="text-brand" />
          Session Cost
        </h2>
        <span className="text-xs text-text-secondary">nodes only, approximate</span>
      </div>

      {error && <p className="text-sm text-danger">{error}</p>}
      {!cost && !error && <p className="text-sm text-text-secondary">Loading…</p>}

      {cost && (
        <>
          <div className="grid grid-cols-3 gap-4 mb-6">
            <div>
              <p className="text-xs text-text-secondary">Uptime</p>
              <p className="text-xl font-bold text-text-primary font-mono">{hm(cost.uptime_hours)}</p>
            </div>
            <div>
              <p className="text-xs text-text-secondary">Burning</p>
              <p className="text-xl font-bold text-text-primary font-mono">{usd(cost.hourly_usd, 3)}/h</p>
            </div>
            <div>
              <p className="text-xs text-text-secondary">This session</p>
              <p className="text-xl font-bold text-text-primary font-mono">{usd(cost.session_usd)}</p>
            </div>
          </div>

          <div className="relative w-full h-2 rounded-full bg-canvas-border overflow-hidden">
            <div className={`h-full ${over ? "bg-amber-500" : "bg-brand"}`} style={{ width: `${pct}%` }} />
            <div
              className="absolute top-0 h-full w-px bg-text-secondary/60"
              style={{ left: `${(idle / cap) * 100}%` }}
            />
          </div>
          <div className="flex justify-between text-xs text-text-secondary mt-2">
            <span>Torn down when idle after {idle} h</span>
            <span>Hard cap in {hm(cost.teardown.hours_to_hard_cap)}</span>
          </div>

          <table className="w-full text-xs mt-6">
            <thead className="text-text-secondary text-left">
              <tr>
                <th className="py-1 font-medium">Node pool</th>
                <th className="py-1 font-medium">Machine</th>
                <th className="py-1 font-medium text-right">Up</th>
                <th className="py-1 font-medium text-right">$/h</th>
              </tr>
            </thead>
            <tbody className="font-mono text-text-primary">
              {cost.nodes.map((n) => (
                <tr key={n.name} className="border-t border-canvas-border/50">
                  <td className="py-1.5">
                    {n.pool ?? "?"}
                    {n.spot && <span className="ml-1 text-text-secondary">(spot)</span>}
                  </td>
                  <td className="py-1.5">{n.machine_type ?? "?"}</td>
                  <td className="py-1.5 text-right">{hm(n.hours)}</td>
                  <td className="py-1.5 text-right">{n.hourly_usd === null ? "?" : usd(n.hourly_usd, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-text-secondary mt-3">
            On-demand list prices; Spot nodes are billed less, so this is an upper bound. Excludes Cloud SQL,
            load balancer and storage.
          </p>
        </>
      )}
    </div>
  );
}
