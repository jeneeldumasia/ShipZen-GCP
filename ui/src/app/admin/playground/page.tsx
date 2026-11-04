"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Bomb, Timer, Trophy, Gauge, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api, PlaygroundData } from "@/lib/api";

const TARGETS = ["random", "shipzen-api", "shipzen-ui", "shipzen-worker", "shipzen-controller"];

function fmtHours(h: number) {
  const hh = Math.floor(h);
  const mm = Math.round((h - hh) * 60);
  return `${hh}h ${String(mm).padStart(2, "0")}m`;
}

/** Admin playground: break things on purpose, watch the money, admire the records. */
export default function PlaygroundPage() {
  const [data, setData] = useState<PlaygroundData | null>(null);
  const [target, setTarget] = useState("random");
  const [busy, setBusy] = useState(false);
  // Chaos round: which component lost a pod, when, and when it was whole again.
  const [round, setRound] = useState<{ deployment: string; pod: string; killedAt: number; healedAt?: number } | null>(null);
  const [now, setNow] = useState(Date.now());
  const sawDip = useRef(false);

  const load = useCallback(async () => {
    try {
      setData(await api.admin.playground());
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not load the playground");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Poll fast while a chaos round is running, slowly otherwise.
  const healing = !!round && !round.healedAt;
  useEffect(() => {
    const t = setInterval(load, healing ? 1000 : 15000);
    return () => clearInterval(t);
  }, [load, healing]);

  useEffect(() => {
    if (!healing) return;
    const t = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(t);
  }, [healing]);

  // Healed = the component dipped below its desired replicas and is back to all ready.
  useEffect(() => {
    if (!round || round.healedAt || !data) return;
    const s = data.platform.find(p => p.name === round.deployment);
    if (!s) return;
    if (s.ready < s.desired) sawDip.current = true;
    if (sawDip.current && s.ready >= s.desired && s.desired > 0) {
      setRound(r => (r ? { ...r, healedAt: Date.now() } : r));
    }
  }, [data, round]);

  async function unleash() {
    setBusy(true);
    try {
      const res = await api.admin.chaos(target);
      sawDip.current = false;
      setRound({ deployment: res.deployment, pod: res.pod, killedAt: Date.now() });
      toast.success(`Deleted ${res.pod}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "The monkey refused");
    } finally {
      setBusy(false);
    }
  }

  const elapsed = round ? ((round.healedAt ?? now) - round.killedAt) / 1000 : 0;
  const s = data?.session;
  const capPct = s ? Math.min(100, (s.uptime_hours / s.hard_cap_hours) * 100) : 0;
  const softPct = s ? (s.soft_limit_hours / s.hard_cap_hours) * 100 : 0;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-display font-bold text-text-primary">Playground</h1>
        <p className="text-sm text-text-secondary">Break things on purpose, watch the meter, admire the records.</p>
      </div>

      {/* Chaos Monkey */}
      <section className="card p-6">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary mb-1"><Bomb size={16} /> Chaos Monkey</h2>
        <p className="text-xs text-text-secondary mb-5">
          Deletes one platform pod and times how long Kubernetes takes to heal it. Only components with 2+ ready
          replicas are eligible, so the platform keeps serving. Never touches user apps.
        </p>
        <div className="flex flex-wrap items-center gap-3 mb-6">
          <select value={target} onChange={e => setTarget(e.target.value)} className="input w-56 font-mono text-sm">
            {TARGETS.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
          <button onClick={unleash} disabled={busy || healing} className="btn-primary disabled:opacity-50">
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Bomb size={14} />} Unleash the monkey
          </button>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          {(data?.platform ?? []).map(p => {
            const hit = round?.deployment === p.name && !round.healedAt;
            const ok = p.ready >= p.desired && p.desired > 0;
            return (
              <div key={p.name} className={`rounded border p-3 transition-colors ${hit ? "border-red-500/60 bg-red-500/5" : "border-canvas-border"}`}>
                <div className="text-xs font-mono text-text-secondary">{p.name.replace("shipzen-", "")}</div>
                <div className="flex gap-1 mt-2">
                  {Array.from({ length: Math.max(p.desired, p.ready) }).map((_, i) => (
                    <span key={i} className={`w-3 h-3 rounded-full ${i < p.ready ? "bg-emerald-500" : "bg-red-500 animate-pulse"}`} />
                  ))}
                </div>
                <div className={`text-xs mt-1 ${ok ? "text-emerald-500" : "text-amber-500"}`}>{p.ready}/{p.desired} ready</div>
              </div>
            );
          })}
        </div>

        {round && (
          <div className="flex items-center gap-4 rounded border border-canvas-border p-4">
            <Timer size={20} className={round.healedAt ? "text-emerald-500" : "text-red-500 animate-pulse"} />
            <div>
              <div className="text-3xl font-mono font-bold text-text-primary">{elapsed.toFixed(1)}s</div>
              <div className="text-xs text-text-secondary">
                {round.healedAt
                  ? `${round.deployment} healed: replacement for ${round.pod} is ready.`
                  : `${round.deployment} lost ${round.pod}… waiting for the replacement to be ready.`}
              </div>
            </div>
          </div>
        )}
      </section>

      {/* Session meter */}
      <section className="card p-6">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary mb-4"><Gauge size={16} /> Session meter</h2>
        {!s ? (
          <p className="text-sm text-text-secondary">Session data unavailable.</p>
        ) : (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-5">
              <Stat label="Cluster up for" value={fmtHours(s.uptime_hours)} />
              <Stat label="Nodes cost now" value={`$${s.hourly_usd.toFixed(3)}/h`} />
              <Stat label="This session (approx.)" value={`$${s.session_usd_estimate.toFixed(2)}`} />
              <Stat label="Hard teardown in" value={fmtHours(s.hours_to_hard_cap)} />
            </div>
            <div className="relative h-3 rounded-full bg-canvas-border/40 overflow-hidden">
              <div className={`h-full ${capPct > softPct ? "bg-amber-500" : "bg-brand"}`} style={{ width: `${capPct}%` }} />
              <div className="absolute top-0 h-full border-l-2 border-dashed border-text-secondary" style={{ left: `${softPct}%` }} />
            </div>
            <div className="flex justify-between text-[11px] text-text-secondary mt-1.5">
              <span>start</span>
              <span style={{ marginLeft: `${softPct - 50}%` }}>{s.soft_limit_hours}h: torn down once idle 60 min</span>
              <span>{s.hard_cap_hours}h cap</span>
            </div>
            <p className="text-[11px] text-text-secondary mt-3">
              Nodes only ({s.nodes.map(n => n.machine).join(", ")}); Cloud SQL, load balancer and disks are extra. $0 once torn down.
            </p>
          </>
        )}
      </section>

      {/* Hall of fame */}
      <section className="card p-6">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary mb-4"><Trophy size={16} /> Hall of fame</h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <Stat label="Fastest build" value={data?.records.fastest_build ? `${data.records.fastest_build.seconds}s` : "–"}
                sub={data?.records.fastest_build?.project} />
          <Stat label="Deploys today" value={String(data?.records.deploys_today ?? "–")} />
          <Stat label="Success rate (7 days)" value={data?.records.success_rate_7d != null ? `${data.records.success_rate_7d}%` : "–"} />
          <div>
            <div className="text-xs text-text-secondary">Most deployed this month</div>
            <ol className="mt-1 space-y-0.5">
              {(data?.records.top_projects_month ?? []).map((p, i) => (
                <li key={p.project} className="text-sm text-text-primary">
                  {["🥇", "🥈", "🥉"][i]} {p.project} <span className="text-text-secondary">· {p.deploys}</span>
                </li>
              ))}
              {data && data.records.top_projects_month.length === 0 && <li className="text-sm text-text-secondary">–</li>}
            </ol>
          </div>
        </div>
      </section>
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <div className="text-xs text-text-secondary">{label}</div>
      <div className="text-xl font-mono font-bold text-text-primary">{value}</div>
      {sub && <div className="text-xs text-text-secondary truncate">{sub}</div>}
    </div>
  );
}
