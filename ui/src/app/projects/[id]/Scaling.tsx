"use client";

import { useState } from "react";
import { Gauge, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api, InstanceSize } from "@/lib/api";

// Mirrors shipzen_common/sizes.py (the API validates the same limits).
const SIZES: Record<InstanceSize, { label: string; cpu: number; memGiB: number; max: number }> = {
  small:  { label: "Small",  cpu: 0.1,  memGiB: 0.125, max: 5 },
  medium: { label: "Medium", cpu: 0.25, memGiB: 0.5,   max: 3 },
  large:  { label: "Large",  cpu: 0.5,  memGiB: 1,     max: 2 },
};
// Approximate on-demand e2 prices in us-central1, per hour.
const VCPU_HOUR = 0.0218;
const GIB_HOUR = 0.0029;

function memLabel(gib: number) {
  return gib < 1 ? `${Math.round(gib * 1024)} MiB` : `${gib} GiB`;
}

/** Instance size and min/max instances of the live release (CPU autoscaling when max > min). */
export function Scaling({ projectId, initial }: {
  projectId: string;
  initial: { size: InstanceSize; min: number; max: number };
}) {
  const [saved, setSaved] = useState(initial);
  const [size, setSize] = useState<InstanceSize>(initial.size);
  const [min, setMin] = useState(initial.min);
  const [max, setMax] = useState(initial.max);
  const [saving, setSaving] = useState(false);

  const cap = SIZES[size].max;
  const dirty = size !== saved.size || min !== saved.min || max !== saved.max;
  const perHour = (n: number) => n * (SIZES[size].cpu * VCPU_HOUR + SIZES[size].memGiB * GIB_HOUR);

  function pickSize(s: InstanceSize) {
    setSize(s);
    const c = SIZES[s].max;
    setMax(m => Math.min(m, c));
    setMin(m => Math.min(m, c));
  }

  async function save() {
    setSaving(true);
    try {
      const p = await api.projects.setScaling(projectId, { instance_size: size, min_instances: min, max_instances: max });
      setSaved({ size: p.instance_size ?? size, min: p.min_instances ?? min, max: p.max_instances ?? max });
      toast.success("Scaling saved. The live release adjusts within a minute or two.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save scaling");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card overflow-hidden mt-6">
      <div className="px-6 py-4 border-b border-canvas-border flex items-center gap-2">
        <Gauge size={16} className="text-text-secondary" />
        <h2 className="text-sm font-semibold text-text-primary">Scaling</h2>
      </div>
      <div className="p-6 space-y-5">
        <div className="grid grid-cols-3 gap-2">
          {(Object.keys(SIZES) as InstanceSize[]).map(s => (
            <button key={s} type="button" onClick={() => pickSize(s)}
              className={`text-left rounded border px-3 py-2 ${s === size ? "border-brand ring-1 ring-brand" : "border-canvas-border hover:border-text-secondary"}`}>
              <div className="text-sm font-semibold text-text-primary">{SIZES[s].label}</div>
              <div className="text-xs text-text-secondary">{SIZES[s].cpu} vCPU · {memLabel(SIZES[s].memGiB)}</div>
            </button>
          ))}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
          <label className="block text-sm text-text-primary">
            Minimum instances: <span className="font-mono">{min}</span>
            <input type="range" min={1} max={cap} value={min} className="w-full mt-2"
              onChange={e => { const v = Number(e.target.value); setMin(v); setMax(m => Math.max(m, v)); }} />
          </label>
          <label className="block text-sm text-text-primary">
            Maximum instances: <span className="font-mono">{max}</span>
            <input type="range" min={1} max={cap} value={max} className="w-full mt-2"
              onChange={e => { const v = Number(e.target.value); setMax(v); setMin(m => Math.min(m, v)); }} />
          </label>
        </div>

        <p className="text-xs text-text-secondary">
          {max > min
            ? `Runs ${min}–${max} instances, adding more when CPU use is above 70%.`
            : `Runs ${min} instance${min > 1 ? "s" : ""}.`}{" "}
          About ${perHour(min).toFixed(3)}{max > min ? `–$${perHour(max).toFixed(3)}` : ""} per hour while the platform is up (nothing while it's torn down).
        </p>

        <div className="flex justify-end">
          <button onClick={save} disabled={!dirty || saving} className="btn-primary disabled:opacity-50">
            {saving && <RefreshCw size={14} className="animate-spin" />}
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
