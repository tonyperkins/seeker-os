"use client";

import { useState } from "react";
import { ChevronDown, FileText, Server, SlidersHorizontal } from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

function ConfigViewer({ data }: { data: Record<string, unknown> | null }) {
  if (!data) {
    return (
      <p className="py-6 text-center text-sm text-muted-foreground">
        No configuration loaded.
      </p>
    );
  }
  return (
    <pre className="overflow-x-auto rounded-md bg-muted/50 p-4 text-xs leading-relaxed font-mono">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

export function SettingsConfigCard({
  scoring,
  sources,
}: {
  scoring: Record<string, unknown> | null;
  sources: Record<string, unknown> | null;
}) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<"scoring" | "sources">("scoring");

  const isScoring = tab === "scoring";

  return (
    <Card>
      <CardHeader
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setOpen((o) => !o);
          }
        }}
        className="flex cursor-pointer select-none flex-row items-start justify-between gap-3"
      >
        <div className="flex min-w-0 flex-col gap-3">
          <div className="flex flex-col gap-1">
            <CardTitle className="flex items-center gap-2">
              <SlidersHorizontal className="size-5 shrink-0" />
              {isScoring ? "Scoring Configuration" : "Sources Configuration"}
            </CardTitle>
            <CardDescription>
              {isScoring ? (
                <>
                  Scoring rubric weights, patterns, and thresholds. From{" "}
                  <code className="text-xs">config/scoring_rubric.yml</code>.
                </>
              ) : (
                <>
                  Source adapters and ATS source mapping. From{" "}
                  <code className="text-xs">config/sources.yml</code>.
                </>
              )}
            </CardDescription>
          </div>
          {open && (
            <div onClick={(e) => e.stopPropagation()}>
              <Tabs
                value={tab}
                onValueChange={(value) => {
                  setTab(value as "scoring" | "sources");
                }}
              >
                <TabsList>
                  <TabsTrigger value="scoring">
                    <FileText className="size-4" />
                    Scoring
                  </TabsTrigger>
                  <TabsTrigger value="sources">
                    <Server className="size-4" />
                    Sources
                  </TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
          )}
        </div>
        <ChevronDown
          className={cn(
            "mt-0.5 size-5 shrink-0 text-muted-foreground transition-transform duration-200",
            open && "rotate-180",
          )}
        />
      </CardHeader>
      {open && (
        <CardContent className="max-h-[28rem] overflow-y-auto">
          <ConfigViewer data={isScoring ? scoring : sources} />
        </CardContent>
      )}
    </Card>
  );
}
