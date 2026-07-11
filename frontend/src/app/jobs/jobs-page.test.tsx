import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { JobSummary, PaginatedJobsResponse } from "@/lib/api";

const { listJobs, replace } = vi.hoisted(() => ({
  listJobs: vi.fn(),
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/lib/use-persistent-state", () => ({
  usePersistentState: <T,>(_key: string, initial: T) => useState(initial),
  useHydrated: () => true,
}));
vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, api: { ...original.api, jobs: { ...original.api.jobs, list: listJobs } } };
});
vi.mock("@/components/add-job-dialog", () => ({ AddJobDialog: () => null }));
vi.mock("@/components/bulk-annotate-skips", () => ({ BulkAnnotateSkips: () => null }));

import JobsPage from "@/app/jobs/page";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function job(id: number, title: string): JobSummary {
  return {
    id, title, company: "Example", score: 7, status: "ready", tier_passed: 4,
    comp_min: null, comp_max: null, location: "Remote", workplace_type: "Remote",
    seniority_level: null, date_posted: "", discovered_at: "", apply_url: "",
    ats_source: null, cross_ref_status: null, is_pinned: false, reject_reason: null,
    reject_details: null, ai_policy: null, source_id: "manual", discovered_query: "",
    run_id: null, is_stale: false, days_since_last_activity: null, has_analysis: false,
    has_research: false, has_resume: false, analysis_verdict: null, net_score: 7,
    score_modifiers: {}, score_reasons: [], has_recruiter: false, recruiter_source: null,
  };
}

describe("JobsPage query behavior", () => {
  beforeEach(() => {
    listJobs.mockReset();
    replace.mockReset();
  });

  it("aborts the older query and ignores its late response", async () => {
    const older = deferred<PaginatedJobsResponse>();
    const newer = deferred<PaginatedJobsResponse>();
    listJobs
      .mockResolvedValueOnce({ jobs: [job(0, "Initial result")], total: 1 })
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(newer.promise);

    render(<JobsPage />);
    await waitFor(() => expect(listJobs).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Initial result")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /company/i }));
    await waitFor(() => expect(listJobs).toHaveBeenCalledTimes(2));
    const oldSignal = listJobs.mock.calls[1][1].signal as AbortSignal;
    fireEvent.click(screen.getByRole("button", { name: /company/i }));
    await waitFor(() => expect(listJobs).toHaveBeenCalledTimes(3));
    expect(oldSignal.aborted).toBe(true);
    expect(listJobs.mock.calls[2][0]).toMatchObject({ sort_by: "company", order: "asc" });

    newer.resolve({ jobs: [job(2, "Current result")], total: 1 });
    expect(await screen.findByText("Current result")).toBeInTheDocument();
    older.resolve({ jobs: [job(1, "Stale result")], total: 1 });
    await Promise.resolve();
    expect(screen.queryByText("Stale result")).not.toBeInTheDocument();
  });

  it("keeps bulk selection scoped to the visible query", async () => {
    listJobs.mockResolvedValue({ jobs: [job(3, "Scoped result")], total: 1 });
    render(<JobsPage />);
    expect(await screen.findByText("Scoped result")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Select Scoped result at Example" }));
    expect(screen.getByText("1 selected on this page")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Status" }));
    await waitFor(() => expect(screen.queryByText("1 selected on this page")).not.toBeInTheDocument());
  });
});
