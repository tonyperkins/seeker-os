"use client";

import { useState } from "react";
import { ChevronDown, FileText, Server } from "lucide-react";
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
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-3">
          <div className="flex flex-col gap-1">
            <CardTitle>
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
          <Tabs
            value={tab}
            onValueChange={(value) => {
              setTab(value as "scoring" | "sources");
              setOpen(true);
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
        <button
          type="button"
          aria-expanded={open}
          aria-label={open ? "Collapse" : "Expand"}
          onClick={() => setOpen((o) => !o)}
          className="-m-1 shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
        >
          <ChevronDown
            className={cn(
              "size-5 transition-transform duration-200",
              open && "rotate-180",
            )}
          />
        </button>
      </CardHeader>
      {open && (
        <CardContent className="max-h-[28rem] overflow-y-auto">
          <ConfigViewer data={isScoring ? scoring : sources} />
        </CardContent>
      )}
    </Card>
  );
}
