"use client";

import { useState, useEffect } from "react";
import { FileText, SlidersHorizontal, ShieldCheck, Building2, Database, Bookmark, SlidersHorizontal as ConfigIcon } from "lucide-react";
import { cn } from "@/lib/utils";

const sections = [
  { id: "profile", label: "Profile & Resume", icon: FileText },
  { id: "bookmarklet", label: "Bookmarklet", icon: Bookmark },
  { id: "accuracy", label: "Accuracy Rules", icon: ShieldCheck },
  { id: "research", label: "Company Research", icon: Building2 },
  { id: "config", label: "Advanced Config", icon: ConfigIcon },
  { id: "backup", label: "Backup & Restore", icon: Database },
];

export function SettingsSectionNav() {
  const [active, setActive] = useState("profile");

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActive(entry.target.id);
          }
        }
      },
      { rootMargin: "-80px 0px -70% 0px" },
    );
    for (const s of sections) {
      const el = document.getElementById(s.id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, []);

  return (
    <nav aria-label="Settings sections" className="sticky top-0 z-30 -mx-4 mb-4 border-b border-border bg-background/95 px-4 py-2 backdrop-blur md:-mx-6 md:px-6">
      <div className="flex gap-1 overflow-x-auto">
        {sections.map((s) => {
          const Icon = s.icon;
          return (
            <a
              key={s.id}
              href={`#${s.id}`}
              className={cn(
                "flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                active === s.id
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
              )}
            >
              <Icon className="size-3.5" />
              {s.label}
            </a>
          );
        })}
      </div>
    </nav>
  );
}
