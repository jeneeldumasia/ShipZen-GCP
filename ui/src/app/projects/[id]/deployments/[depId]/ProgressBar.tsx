"use client";

import { Check, Loader2 } from "lucide-react";

type DeploymentState = "Queued" | "Building" | "Deploying" | "Verifying" | "Running" | "Failed" | "Cancelled";

const STATES = ["Queued", "Building", "Deploying", "Verifying", "Running"];

export function ProgressBar({ state }: { state: DeploymentState }) {
  if (state === "Failed" || state === "Cancelled") {
    return (
      <div className="w-full max-w-3xl mx-auto mb-20 relative py-4">
        <div className="absolute left-0 top-1/2 -translate-y-1/2 w-full h-[2px] bg-white/5" />
        <div className="absolute left-0 top-1/2 -translate-y-1/2 w-full h-[2px] bg-red-500/50 shadow-[0_0_15px_rgba(239,68,68,0.5)]" />
        
        <div className="relative z-10 flex flex-col items-center gap-3 bg-background px-6 mx-auto w-max">
          <div className="w-11 h-11 rounded-full border border-red-500/50 bg-red-500/10 flex items-center justify-center text-red-500 shadow-[0_0_20px_rgba(239,68,68,0.3)] backdrop-blur-md">
            <span className="text-sm font-bold font-mono">!</span>
          </div>
          <span className="text-[11px] font-mono uppercase tracking-[0.2em] text-red-500 font-bold absolute top-[60px] whitespace-nowrap drop-shadow-[0_0_8px_rgba(239,68,68,0.5)]">{state}</span>
        </div>
      </div>
    );
  }

  const currentIndex = STATES.indexOf(state);
  const activeIndex = currentIndex === -1 ? 0 : currentIndex;
  const progressPercent = (activeIndex / (STATES.length - 1)) * 100;

  return (
    <div className="w-full max-w-3xl mx-auto mb-20 relative px-4">
      {/* Background track */}
      <div className="absolute left-[32px] right-[32px] top-[22px] h-[2px] bg-white/5 rounded-full overflow-hidden">
        {/* Animated active progress fill */}
        <div 
          className="absolute left-0 top-0 h-full bg-gradient-to-r from-white/10 via-white/80 to-white transition-all duration-1000 ease-[cubic-bezier(0.22,1,0.36,1)] shadow-[0_0_15px_rgba(255,255,255,0.7)]"
          style={{ width: `${progressPercent}%` }}
        />
      </div>

      <div className="relative z-10 flex items-center justify-between">
        {STATES.map((step, index) => {
          const isCompleted = index < activeIndex;
          const isCurrent = index === activeIndex;

          return (
            <div key={step} className="flex flex-col items-center bg-background px-3">
              {/* Node */}
              <div className="relative flex items-center justify-center">
                {isCompleted ? (
                  <div className="w-11 h-11 rounded-full bg-white/10 border border-white/20 flex items-center justify-center text-white backdrop-blur-sm transition-all duration-500">
                    <Check size={16} strokeWidth={2.5} />
                  </div>
                ) : isCurrent ? (
                  <div className="w-11 h-11 rounded-full flex items-center justify-center relative">
                    <div className="absolute inset-0 rounded-full border border-white/30 animate-[ping_2.5s_cubic-bezier(0,0,0.2,1)_infinite]" />
                    <div className="absolute inset-0 rounded-full bg-white/10 border-2 border-white backdrop-blur-md shadow-[0_0_20px_rgba(255,255,255,0.4)]" />
                    <Loader2 size={16} className="text-white animate-spin relative z-10" />
                  </div>
                ) : (
                  <div className="w-11 h-11 rounded-full bg-transparent border border-white/10 flex items-center justify-center text-white/20 transition-all duration-500">
                    <span className="text-[11px] font-mono font-medium">{index + 1}</span>
                  </div>
                )}
              </div>
              
              {/* Label */}
              <span 
                className={`text-[10px] font-mono uppercase tracking-[0.2em] transition-all duration-500 absolute top-[60px] whitespace-nowrap
                  ${isCurrent ? "text-white font-bold drop-shadow-[0_0_8px_rgba(255,255,255,0.5)]" : 
                    isCompleted ? "text-white/60" : "text-white/20"}`}
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
