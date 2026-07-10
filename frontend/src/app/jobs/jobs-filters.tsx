"use client";

import { Search, Loader2, RotateCcw, Filter, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { CollapsibleCard } from "@/components/ui/collapsible-card";
import { STATUS_OPTIONS, SOURCE_OPTIONS, VERDICT_OPTIONS } from "./jobs-helpers";

interface JobsFiltersProps {
  status: string;
  minScore: string;
  company: string;
  search: string;
  source: string;
  runId: string;
  verdict: string;
  hideRejected: boolean;
  hideSkipped: boolean;
  loading: boolean;
  setStatus: (v: string) => void;
  setMinScore: (v: string) => void;
  setCompany: (v: string) => void;
  setSearch: (v: string) => void;
  setSource: (v: string) => void;
  setRunId: (v: string) => void;
  setVerdict: (v: string) => void;
  setHideRejected: (v: boolean) => void;
  setHideSkipped: (v: boolean) => void;
  onReset: () => void;
  onRefresh: () => void;
}

export function JobsFilters(props: JobsFiltersProps) {
  const {
    status, minScore, company, search, source, runId, verdict,
    hideRejected, hideSkipped, loading,
    setStatus, setMinScore, setCompany, setSearch, setSource,
    setRunId, setVerdict, setHideRejected, setHideSkipped,
    onReset, onRefresh,
  } = props;

  const activeCount = [status, source, minScore, runId, search, company, verdict, hideRejected ? "hr" : null, hideSkipped ? "hs" : null].filter(Boolean).length;

  return (
    <CollapsibleCard
      title={
        <div className="flex items-center gap-2">
          Filters
          {activeCount > 0 && (
            <Badge variant="secondary" className="h-4 px-1.5 text-[10px]">
              {activeCount}
            </Badge>
          )}
        </div>
      }
      icon={Filter}
      defaultOpen={true}
      action={
        <Button
          variant="ghost"
          size="sm"
          onClick={onReset}
          title="Clear all filters"
          className="h-7 text-xs text-muted-foreground hover:text-foreground"
        >
          <RotateCcw className="size-3.5" />
          Reset
        </Button>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-start gap-4 sm:gap-6">
          <div className="flex flex-wrap items-center gap-2">
            <span className="min-w-[48px] text-xs font-normal text-muted-foreground">Status</span>
            <button
              onClick={() => setStatus("")}
              className={`rounded-md border px-3 py-1 text-xs font-medium transition-all ${
                status === ""
                  ? "border-foreground/20 bg-foreground/20 text-foreground"
                  : "border-border bg-transparent text-muted-foreground hover:border-foreground/30 hover:text-foreground"
              }`}
            >
              All
            </button>
            {STATUS_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setStatus(opt.value)}
                className={`rounded-md border px-3 py-1 text-xs font-medium transition-all ${
                  status === opt.value
                    ? "border-foreground/20 bg-foreground/20 text-foreground"
                    : "border-border bg-transparent text-muted-foreground hover:border-foreground/30 hover:text-foreground"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>

          <Separator orientation="vertical" className="hidden h-6 self-center bg-border/50 sm:block" />

          <div className="flex flex-wrap items-center gap-2">
            <span className="min-w-[44px] text-xs font-normal text-muted-foreground">Source</span>
            <button
              onClick={() => setSource("")}
              className={`rounded-md border px-3 py-1 text-xs font-medium transition-all ${
                source === ""
                  ? "border-foreground/20 bg-foreground/20 text-foreground"
                  : "border-border bg-transparent text-muted-foreground hover:border-foreground/30 hover:text-foreground"
              }`}
            >
              All
            </button>
            {SOURCE_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setSource(opt.value)}
                className={`rounded-md border px-3 py-1 text-xs font-medium transition-all ${
                  source === opt.value
                    ? "border-foreground/20 bg-foreground/20 text-foreground"
                    : "border-border bg-transparent text-muted-foreground hover:border-foreground/30 hover:text-foreground"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        <Separator className="bg-border/50" />

        <div className="flex flex-wrap items-center gap-2">
          <span className="min-w-[48px] text-xs font-normal text-muted-foreground">Verdict</span>
          <button
            onClick={() => setVerdict("")}
            className={`rounded-md border px-3 py-1 text-xs font-medium transition-all ${
              verdict === ""
                ? "border-foreground/20 bg-foreground/20 text-foreground"
                : "border-border bg-transparent text-muted-foreground hover:border-foreground/30 hover:text-foreground"
            }`}
          >
            All
          </button>
          {VERDICT_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setVerdict(opt.value)}
              className={`rounded-md border px-3 py-1 text-xs font-medium transition-all ${
                verdict === opt.value
                  ? opt.activeClass
                  : "border-border bg-transparent text-muted-foreground hover:border-foreground/30 hover:text-foreground"
              }`}
            >
              {opt.label}
            </button>
          ))}
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <span className="text-xs font-normal text-muted-foreground">Hide</span>
            <button
              onClick={() => setHideRejected(!hideRejected)}
              className={`rounded-md border px-3 py-1 text-xs font-medium transition-all ${
                hideRejected
                  ? "border-border bg-red-600 text-white"
                  : "border-border bg-transparent text-muted-foreground hover:border-foreground/30 hover:text-foreground"
              }`}
            >
              Rejected
            </button>
            <button
              onClick={() => setHideSkipped(!hideSkipped)}
              className={`rounded-md border px-3 py-1 text-xs font-medium transition-all ${
                hideSkipped
                  ? "border-foreground/20 bg-foreground/20 text-foreground"
                  : "border-border bg-transparent text-muted-foreground hover:border-foreground/30 hover:text-foreground"
              }`}
            >
              Skipped
            </button>
          </div>
        </div>

        <Separator className="bg-border/50" />
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-muted-foreground">Min score</label>
            <Input
              type="number"
              min={0}
              max={100}
              step="0.1"
              placeholder="0"
              value={minScore}
              onChange={(e) => setMinScore(e.target.value)}
              className="w-24"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-muted-foreground">Run ID</label>
            <Input
              type="text"
              placeholder="e.g. 0627"
              value={runId}
              onChange={(e) => setRunId(e.target.value)}
              className="w-28"
            />
          </div>

          <div className="flex flex-1 flex-col gap-1.5">
            <label className="text-xs font-semibold text-muted-foreground">Search</label>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                type="text"
                placeholder="Search title, company, location, reject reason…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-8 pr-8"
              />
              {search && (
                <button
                  onClick={() => setSearch("")}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  <X className="size-4" />
                </button>
              )}
            </div>
          </div>

          <Button size="sm" onClick={onRefresh} disabled={loading}>
            {loading ? <Loader2 className="animate-spin" /> : <Search className="size-4" />}
            Refresh
          </Button>
        </div>
      </div>
    </CollapsibleCard>
  );
}
