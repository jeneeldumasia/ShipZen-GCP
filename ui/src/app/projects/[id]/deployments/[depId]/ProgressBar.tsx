"use client";

import { Check, CircleDot, Clock, LayoutGrid } from "lucide-react";

type DeploymentState = "Queued" | "Building" | "Deploying" | "Verifying" | "Running" | "Failed" | "Cancelled";

const STATES = ["Queued", "Building", "Deploying", "Verifying", "Running"];

export function ProgressBar({ state }: { state: DeploymentState }) {
  if (state === "Failed" || state === "Cancelled") {
    return (
      <div className="w-full max-w-3xl mx-auto mb-12">
        <div className="flex items-center justify-between relative">
          <div className="absolute left-0 top-1/2 -translate-y-1/2 w-full h-0.5 bg-text-secondary/10" />
          <div className="absolute left-0 top-1/2 -translate-y-1/2 w-full h-0.5 bg-red-500/50" />
          
          <div className="relative z-10 flex flex-col items-center gap-2 bg-background px-4">
            <div className="w-8 h-8 rounded-full border-2 border-red-500 bg-background flex items-center justify-center text-red-500 shadow-[0_0_15px_rgba(239,68,68,0.3)]">
              <span className="text-xs font-bold font-mono">!</span>
            </div>
            <span className="text-[10px] font-mono uppercase tracking-widest text-red-500 font-bold">{state}</span>
          </div>
        </div>
      </div>
    );
  }

  const currentIndex = STATES.indexOf(state);
  // If state is not in the array (shouldn't happen for active states), default to Queued
  const activeIndex = currentIndex === -1 ? 0 : currentIndex;

  return (
    <div className="w-full max-w-3xl mx-auto mb-12">
      <div className="flex items-center justify-between relative">
        {/* Background Line */}
        <div className="absolute left-0 top-1/2 -translate-y-1/2 w-full h-0.5 bg-text-secondary/10" />
        
        {/* Active Line */}
        <div 
          className="absolute left-0 top-1/2 -translate-y-1/2 h-0.5 bg-brand transition-all duration-700 shadow-[0_0_10px_rgba(var(--brand-rgb),0.5)]"
          style={{ width: `${(activeIndex / (STATES.length - 1)) * 100}%` }}
        />

        {STATES.map((step, index) => {
          const isCompleted = index < activeIndex;
          const isCurrent = index === activeIndex;
          const isFuture = index > activeIndex;

          return (
            <div key={step} className="relative z-10 flex flex-col items-center gap-2 bg-background px-2 sm:px-4">
              <div 
                className={`w-8 h-8 rounded-full border-2 flex items-center justify-center transition-all duration-500
                  ${isCompleted ? "border-brand bg-brand text-background" : 
                    isCurrent ? "border-brand bg-background text-brand shadow-[0_0_15px_rgba(var(--brand-rgb),0.3)] animate-pulse-slow" : 
                    "border-text-secondary/20 bg-background text-text-secondary/20"}`}
              >
                {isCompleted ? (
                  <Check size={14} strokeWidth={3} />
                ) : isCurrent ? (
                  <CircleDot size={14} />
                ) : (
                  <span className="text-[10px] font-mono font-bold">{index + 1}</span>
                )}
              </div>
              <span 
                className={`text-[10px] font-mono uppercase tracking-widest transition-colors duration-500 hidden sm:block
                  ${isCurrent ? "text-brand font-bold" : 
                    isCompleted ? "text-text-primary" : "text-text-secondary/40"}`}
              >
                {step}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
