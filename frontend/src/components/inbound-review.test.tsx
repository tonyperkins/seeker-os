import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { InboundMessage, InboundStatus, JobSummary } from "@/lib/api";

const { confirm, dismiss, inboundList, jobsList, status } = vi.hoisted(() => ({
  confirm: vi.fn(),
  dismiss: vi.fn(),
  inboundList: vi.fn(),
  jobsList: vi.fn(),
  status: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: {
      ...original.api,
      jobs: { ...original.api.jobs, list: jobsList },
      inbound: {
        ...original.api.inbound,
        status,
        list: inboundList,
        confirm,
        dismiss,
      },
    },
  };
});

import { InboundReview } from "@/components/inbound-review";

const inboundStatus: InboundStatus = {
  enabled: true,
  account_key: "dedicated_gmail",
  dedicated_account_address: "inbound@example.com",
  primary_account_address: "primary@example.com",
  message_id_equality_verified: false,
  oauth: { connected: true, account_email: "inbound@example.com" },
  history_id: "123",
  last_success_at: null,
  last_error: null,
  sync_locked: false,
  pending_count: 1,
};

const activeJob: JobSummary = {
  id: 7, title: "Platform Engineer", company: "Acme", score: 8, status: "applied", tier_passed: 4,
  comp_min: null, comp_max: null, location: "Remote", workplace_type: "Remote", seniority_level: null,
  date_posted: "", discovered_at: "", apply_url: "", ats_source: null, cross_ref_status: null,
  is_pinned: false, reject_reason: null, reject_details: null, ai_policy: null, source_id: "manual",
  discovered_query: "", run_id: null, preference_rank: null, is_stale: false, days_since_last_activity: null,
  has_analysis: false, has_research: false, has_resume: false, analysis_verdict: null, net_score: 8,
  score_modifiers: {}, score_reasons: [], has_recruiter: false, recruiter_source: null,
};

const inboundMessage: InboundMessage = {
  id: 5, account_key: "dedicated_gmail", gmail_message_id: "gmail-5", gmail_thread_id: "thread-5",
  rfc822_message_id: "<mail@example.com>", sender_address: "recruiting@acme.com", sender_domain: "acme.com",
  subject: "Interview update", received_at: "2026-07-20T12:00:00+00:00", suggested_job_id: 7,
  suggested_job_title: "Platform Engineer", suggested_job_company: "Acme", final_job_id: null,
  match_score: 0.82, match_features: {}, match_candidates: [{ job_id: 7, score: 0.82, features: [] }],
  matcher_version: "inbound-v1", state: "matched", decision: null, decided_at: null,
  confirmed_event_id: null, primary_gmail_link: null,
};

describe("InboundReview", () => {
  beforeEach(() => {
    status.mockResolvedValue(inboundStatus);
    inboundList.mockResolvedValue([inboundMessage]);
    jobsList.mockResolvedValue({ jobs: [activeJob], total: 1 });
    confirm.mockResolvedValue(inboundMessage);
    dismiss.mockResolvedValue(inboundMessage);
  });

  it("shows ranked evidence and confirms its suggested application", async () => {
    render(<InboundReview />);

    expect(await screen.findByText("Interview update")).toBeInTheDocument();
    expect(screen.getByText(/Acme — Platform Engineer/)).toBeInTheDocument();
    expect(screen.getByText(/Primary-mailbox links are disabled/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(confirm).toHaveBeenCalledWith(5, 7));
  });

  it("lets unmatched account mail be dismissed", async () => {
    inboundList.mockResolvedValue([{ ...inboundMessage, id: 6, state: "unmatched", suggested_job_id: null }]);
    render(<InboundReview />);

    expect(await screen.findByText(/Google account and security mail is expected here/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(dismiss).toHaveBeenCalledWith(6));
  });

  it("renders a primary Gmail link as a link rather than a native button", async () => {
    inboundList.mockResolvedValue([{
      ...inboundMessage,
      primary_gmail_link: "https://mail.google.com/mail/u/example/#search/rfc822msgid%3Aexample",
    }]);
    render(<InboundReview />);

    const link = await screen.findByRole("link", { name: /open in primary gmail/i });
    expect(link).toHaveAttribute("target", "_blank");
  });
});
