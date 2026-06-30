"use client";

import { useSyncExternalStore, useCallback } from "react";
import { Sun, Moon } from "lucide-react";
import { Button } from "@/components/ui/button";

type Theme = "light" | "dark";

function getTheme(): Theme {
  if (typeof document === "undefined") return "light";
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function subscribe(callback: () => void): () => void {
  window.addEventListener("seeker-os-theme-change", callback);
  return () => window.removeEventListener("seeker-os-theme-change", callback);
}

export function ThemeToggle() {
  const theme = useSyncExternalStore(subscribe, getTheme, () => "light" as Theme);

  const toggle = useCallback(() => {
    const next: Theme = theme === "light" ? "dark" : "light";
    localStorage.setItem("seeker-os-theme", next);
    document.cookie = `seeker-os-theme=${next};path=/;max-age=31536000;samesite=lax`;
    document.documentElement.classList.toggle("dark", next === "dark");
    // Force re-render by dispatching a storage event won't work same-tab,
    // so we dispatch a custom event that our subscribe can listen for.
    window.dispatchEvent(new Event("seeker-os-theme-change"));
  }, [theme]);

  return (
    <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle theme">
      {theme === "light" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  );
}
