"use client";

import { Suspense, useEffect, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { AddJobDialog } from "@/components/add-job-dialog";
import { BulkAnnotateSkips } from "@/components/bulk-annotate-skips";
import type { JobSortKey } from "@/lib/api";
import { useJobsQuery } from "./use-jobs-query";
import { useBulkActions } from "./use-bulk-actions";
import { JobsFilters } from "./jobs-filters";
import { JobsTable } from "./jobs-table";
import { JobsPagination } from "./jobs-pagination";
import { BulkActionToolbar } from "./bulk-action-toolbar";

const PAGE_SIZE = 50;

export default function JobsPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center gap-2 py-20 text-sm text-muted-foreground">
        <Loader2 className="animate-spin" />
        Loading jobs…
      </div>
    }>
      <JobsPageInner />
    </Suspense>
  );
}

function JobsPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const {
    state,
    setters,
    jobs,
    total,
    loading,
    error,
    hydrated,
    filterKey,
    refetch,
    resetFilters,
  } = useJobsQuery();

  const {
    selection,
    bulkLoading,
    bulkError,
    bulkProgress,
    toggleJob,
    toggleAll,
    allSelected,
    someSelected,
    clearSelection,
    runBulkAction,
  } = useBulkActions();

  const selectionScope = `${filterKey}|${state.page}|${state.sortKey}|${state.sortDir}`;
  const scopedSelectedIds = selection.scope === selectionScope ? selection.ids : new Set<number>();

  useEffect(() => {
    if (!hydrated) return;
    const params = new URLSearchParams();
    if (state.status) params.set("status", state.status);
    if (state.minScore) params.set("min_score", state.minScore);
    if (state.company) params.set("company", state.company);
    if (state.search) params.set("search", state.search);
    if (state.source) params.set("source", state.source);
    if (state.runId) params.set("run_id", state.runId);
    if (state.verdict) params.set("verdict", state.verdict);
    if (state.hideRejected) params.set("hide_rejected", "1");
    if (state.hideSkipped) params.set("hide_skipped", "1");
    params.set("sort_by", state.sortKey);
    params.set("order", state.sortDir);
    if (state.page > 1) params.set("page", String(state.page));
    const qs = params.toString();
    router.replace(qs ? `/jobs?${qs}` : "/jobs", { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.status, state.minScore, state.company, state.search, state.source, state.runId, state.verdict, state.hideRejected, state.hideSkipped, state.sortKey, state.sortDir, state.page, router, hydrated]);

  function toggleSort(key: JobSortKey) {
    if (state.sortKey === key) {
      setters.setSortDir(state.sortDir === "asc" ? "desc" : "asc");
    } else {
      setters.setSortKey(key);
      setters.setSortDir("desc");
    }
  }

  const displayedJobs = jobs ?? [];
  const isAllSelected = allSelected(displayedJobs.map((j) => j.id), selectionScope);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Jobs</h1>
        </div>
        <div className="flex items-center gap-2">
          <BulkAnnotateSkips />
          <AddJobDialog onCreated={() => refetch()} />
        </div>
      </div>

      <JobsFilters
        status={state.status}
        minScore={state.minScore}
        company={state.company}
        search={state.search}
        source={state.source}
        runId={state.runId}
        verdict={state.verdict}
        hideRejected={state.hideRejected}
        hideSkipped={state.hideSkipped}
        loading={loading}
        setStatus={setters.setStatus}
        setMinScore={setters.setMinScore}
        setCompany={setters.setCompany}
        setSearch={setters.setSearch}
        setSource={setters.setSource}
        setRunId={setters.setRunId}
        setVerdict={setters.setVerdict}
        setHideRejected={setters.setHideRejected}
        setHideSkipped={setters.setHideSkipped}
        onReset={resetFilters}
        onRefresh={refetch}
      />

      <BulkActionToolbar
        selectedCount={scopedSelectedIds.size}
        bulkLoading={bulkLoading}
        bulkError={bulkError}
        bulkProgress={bulkProgress}
        onBulkAction={(action, fn) => void runBulkAction(action, fn, refetch)}
        onClear={() => clearSelection(selectionScope)}
      />

      <JobsTable
        jobs={jobs}
        loading={loading}
        error={error}
        sortKey={state.sortKey}
        sortDir={state.sortDir}
        selectedIds={scopedSelectedIds}
        allSelected={isAllSelected}
        onToggleSort={toggleSort}
        onToggleJob={(id) => toggleJob(id, selectionScope)}
        onToggleAll={() => toggleAll(displayedJobs.map((j) => j.id), selectionScope)}
      />

      <JobsPagination
        page={state.page}
        total={total}
        pageSize={PAGE_SIZE}
        displayedCount={displayedJobs.length}
        loading={loading}
        onPageChange={setters.setPage}
      />
    </div>
  );
}
