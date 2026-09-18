"use client";

import { ServerCrash } from "lucide-react";

export function SystemControls() {

  return (
    <div className="card p-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold text-text-primary mb-1 flex items-center gap-2">
            <ServerCrash size={18} className="text-brand" />
            System Operations
          </h2>
          <p className="text-sm text-text-secondary mb-4">
            System pod operations are currently disabled because ArgoCD automatically reverts manual interventions.
          </p>
        </div>
      </div>
    </div>
  );
}
