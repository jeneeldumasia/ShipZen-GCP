"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export function ProjectShortcuts({ projectId }: { projectId: string }) {
  const router = useRouter();

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      // Shortcut D: Deploy
      if (e.key.toLowerCase() === "d" && !e.metaKey && !e.ctrlKey && e.target === document.body) {
        e.preventDefault();
        router.push(`/projects/${projectId}/deployments/new`);
      }
    };

    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, [router, projectId]);

  return null;
}
