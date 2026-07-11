"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { FileText, Bookmark, ShieldCheck, Building2, SlidersHorizontal as ConfigIcon, Database } from "lucide-react";
import { cn } from "@/lib/utils";
import { SettingsClient } from "@/components/settings-client";
import { SettingsConfigCard } from "@/components/settings-config-card";
import { AccuracyRulesCard } from "@/components/accuracy-rules-card";
import { CompanyResearchSettingsCard } from "@/components/company-research-settings-card";
import { BackupRestoreCard } from "@/components/backup-restore-card";
import { BookmarkletCard } from "@/components/bookmarklet-card";
import type { SettingsResponse, ProfileData, FiltersData, AccuracyRule } from "@/lib/api";

const TABS = [
  { id: "profile", label: "Profile & Resume", icon: FileText },
  { id: "bookmarklet", label: "Bookmarklet", icon: Bookmark },
  { id: "accuracy", label: "Accuracy Rules", icon: ShieldCheck },
  { id: "research", label: "Company Research", icon: Building2 },
  { id: "config", label: "Advanced Config", icon: ConfigIcon },
  { id: "backup", label: "Backup & Restore", icon: Database },
] as const;

type TabId = (typeof TABS)[number]["id"];

export function SettingsTabs({
  profile,
  filters,
  accuracyRules,
  scoring,
  sources,
}: {
  profile: ProfileData | null;
  filters: FiltersData | null;
  accuracyRules: AccuracyRule[];
  scoring: Record<string, unknown> | null;
  sources: Record<string, unknown> | null;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [active, setActive] = useState<TabId>("profile");

  useEffect(() => {
    const tab = searchParams.get("tab");
    if (tab && TABS.some((t) => t.id === tab)) {
      setActive(tab as TabId);
    }
  }, [searchParams]);

  const switchTab = useCallback(
    (tabId: TabId) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("tab", tabId);
      router.push(`/settings?${params.toString()}`, { scroll: false });
      setActive(tabId);
    },
    [router, searchParams],
  );

  return (
    <div className="flex flex-col gap-4">
      <nav aria-label="Settings sections" className="sticky top-0 z-30 -mx-4 border-b border-border bg-background/95 px-4 py-2 backdrop-blur md:-mx-6 md:px-6">
        <div className="flex gap-1 overflow-x-auto">
          {TABS.map((t) => {
            const Icon = t.icon;
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => switchTab(t.id)}
                className={cn(
                  "flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                  active === t.id
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
                )}
              >
                <Icon className="size-3.5" />
                {t.label}
              </button>
            );
          })}
        </div>
      </nav>

      <div className="flex flex-col gap-6">
        {active === "profile" && (
          <SettingsClient profile={profile} filters={filters} />
        )}
        {active === "bookmarklet" && <BookmarkletCard />}
        {active === "accuracy" && <AccuracyRulesCard initialRules={accuracyRules} />}
        {active === "research" && <CompanyResearchSettingsCard />}
        {active === "config" && (
          <SettingsConfigCard scoring={scoring} sources={sources} />
        )}
        {active === "backup" && <BackupRestoreCard />}
      </div>
    </div>
  );
}
