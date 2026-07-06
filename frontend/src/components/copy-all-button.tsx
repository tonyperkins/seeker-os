"use client";

import { useState } from "react";
import { Copy, Check, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api, type JobDetail, type JobAnalysisResult, type CompanyResearchResult } from "@/lib/api";
import { formatDate } from "@/lib/date";

function formatComp(job: JobDetail): string {
  if (job.comp_min == null && job.comp_max == null) return "Not listed";
  const fmt = (n: number) => `$${(n / 1000).toFixed(0)}k`;
  if (job.comp_min != null && job.comp_max != null) {
    return `${fmt(job.comp_min)} – ${fmt(job.comp_max)}${job.comp_currency ? ` ${job.comp_currency}` : ""}`;
  }
  if (job.comp_min != null) return `${fmt(job.comp_min)}+`;
  return `≤${fmt(job.comp_max as number)}`;
}

function formatAnalysis(a: JobAnalysisResult): string {
  const lines: string[] = [];
  lines.push(`Verdict: ${a.verdict}`);
  lines.push(`Score: ${a.weighted_score.toFixed(1)}`);
  lines.push(`Confidence: ${Math.round(a.confidence * 100)}%`);
  lines.push(`Summary: ${a.one_line}`);

  if (a.hard_blockers.length > 0) {
    lines.push("\nHard Blockers:");
    a.hard_blockers.forEach(b => lines.push(`  - ${b.type}: ${b.detail}`));
  }

  if (a.named_gaps.length > 0) {
    lines.push("\nNamed Gaps:");
    a.named_gaps.forEach(g => lines.push(`  - ${g.area} (${g.severity}): JD requires ${g.jd_requires}, actual ${g.candidate_actual}`));
  }

  if (a.rubric_breakdown.length > 0) {
    lines.push("\nRubric Breakdown:");
    a.rubric_breakdown.forEach(d => lines.push(`  - ${d.dimension}: ${d.weighted.toFixed(1)} (${d.raw.toFixed(1)} × ${d.weight.toFixed(1)})${d.note ? ` — ${d.note}` : ""}`));
  }

  if (a.bonuses_applied.length > 0) lines.push(`\nBonuses: ${a.bonuses_applied.join(", ")}`);
  if (a.penalties_applied.length > 0) lines.push(`Penalties: ${a.penalties_applied.join(", ")}`);
  if (a.comp.note) lines.push(`\nCompensation: ${a.comp.note}`);
  if (a.positioning.note) lines.push(`Positioning: ${a.positioning.note}`);
  if (a.company_fit.note) lines.push(`Company Fit: ${a.company_fit.note}`);

  if (a.tailoring.lead_with.length > 0) lines.push(`\nLead with: ${a.tailoring.lead_with.join(", ")}`);
  if (a.tailoring.reframe_summary) lines.push(`Reframe: ${a.tailoring.reframe_summary}`);
  if (a.tailoring.do_not_claim.length > 0) lines.push(`Do NOT claim: ${a.tailoring.do_not_claim.join(", ")}`);

  if (a.red_flags.length > 0) {
    lines.push("\nRed Flags:");
    a.red_flags.forEach(f => lines.push(`  - ${f}`));
  }

  return lines.join("\n");
}

function formatResearch(r: CompanyResearchResult): string {
  const lines: string[] = [];

  if (r.summary) {
    lines.push(r.summary);
    lines.push(`Confidence: ${Math.round(r.overall_confidence * 100)}%`);
  }

  if (r.wikipedia) {
    lines.push(`\nAbout: ${r.wikipedia.extract}`);
  }

  if (r.funding) {
    lines.push("\nFunding & Stage:");
    if (r.funding.stage) lines.push(`  Stage: ${r.funding.stage}`);
    if (r.funding.public) lines.push(`  Public: Yes`);
    if (r.funding.founded) lines.push(`  Founded: ${r.funding.founded}`);
    if (r.funding.hq) lines.push(`  HQ: ${r.funding.hq}`);
    if (r.funding.total_raised_usd != null) lines.push(`  Total raised: $${(r.funding.total_raised_usd / 1e6).toFixed(0)}M`);
    if (r.funding.valuation_usd != null) lines.push(`  Valuation: $${(r.funding.valuation_usd / 1e6).toFixed(0)}M`);
    if (r.funding.headcount != null) lines.push(`  Headcount: ${r.funding.headcount.toLocaleString()}`);
    if (r.funding.headcount_trend) lines.push(`  Trend: ${r.funding.headcount_trend}`);
    if (r.funding.financial_health) lines.push(`  Health: ${r.funding.financial_health}`);
    if (r.funding.layoffs.length > 0) {
      lines.push("  Layoffs:");
      r.funding.layoffs.forEach(l => {
        let s = `    ${l.date || ""}`;
        if (l.pct != null) s += ` (${l.pct}%)`;
        if (l.count != null) s += ` · ${l.count} employees`;
        lines.push(s);
      });
    }
  }

  if (r.sentiment) {
    lines.push("\nEmployee Sentiment:");
    if (r.sentiment.overall_rating_estimate != null) lines.push(`  Rating: ${r.sentiment.overall_rating_estimate.toFixed(1)} / ${r.sentiment.rating_scale}`);
    if (r.sentiment.ceo_approval_pct != null) lines.push(`  CEO approval: ${r.sentiment.ceo_approval_pct.toFixed(0)}%`);
    if (r.sentiment.recommend_pct != null) lines.push(`  Recommend: ${r.sentiment.recommend_pct.toFixed(0)}%`);
    if (r.sentiment.positives.length > 0) {
      lines.push("  Positives:");
      r.sentiment.positives.forEach(t => lines.push(`    + ${t.theme} (${t.frequency})${t.paraphrase ? `: ${t.paraphrase}` : ""}`));
    }
    if (r.sentiment.negatives.length > 0) {
      lines.push("  Negatives:");
      r.sentiment.negatives.forEach(t => lines.push(`    - ${t.theme} (${t.frequency})${t.paraphrase ? `: ${t.paraphrase}` : ""}`));
    }
  }

  if (r.fit) {
    lines.push("\nFit Signals:");
    if (r.fit.remote_policy) lines.push(`  Remote: ${r.fit.remote_policy}`);
    if (r.fit.size_bucket) lines.push(`  Size: ${r.fit.size_bucket}`);
    if (r.fit.ic_vs_mgmt_culture) lines.push(`  Culture: ${r.fit.ic_vs_mgmt_culture}`);
    if (r.fit.comp_band) lines.push(`  Comp: ${r.fit.comp_band}`);
    if (r.fit.remote_walkback) lines.push(`  Walkback: ${r.fit.remote_walkback}`);
  }

  if (r.verdict_flags.green.length > 0) lines.push(`\nGreen flags: ${r.verdict_flags.green.join(", ")}`);
  if (r.verdict_flags.red.length > 0) lines.push(`Red flags: ${r.verdict_flags.red.join(", ")}`);
  if (r.verdict_flags.watch.length > 0) lines.push(`Watch: ${r.verdict_flags.watch.join(", ")}`);

  return lines.join("\n");
}

export function CopyAllButton({ job }: { job: JobDetail }) {
  const [copied, setCopied] = useState(false);
  const [loading, setLoading] = useState(false);

  async function copyAll() {
    setLoading(true);
    try {
      const parts: string[] = [];

      // Details
      parts.push("=== DETAILS ===");
      parts.push(`Title: ${job.title}`);
      parts.push(`Company: ${job.company}`);
      parts.push(`Compensation: ${formatComp(job)}`);
      parts.push(`Location: ${job.location}`);
      parts.push(`Workplace: ${job.workplace_type}`);
      parts.push(`Seniority: ${job.seniority_level || "—"}`);
      parts.push(`Role type: ${job.role_type || "—"}`);
      parts.push(`Date posted: ${formatDate(job.date_posted)}`);
      parts.push(`Discovered: ${formatDate(job.discovered_at)}`);
      parts.push(`ATS source: ${job.ats_source || "—"}`);
      parts.push(`Commitment: ${job.commitment.join(", ") || "—"}`);
      parts.push(`Countries: ${job.workplace_countries.join(", ") || "—"}`);

      // Score Breakdown
      parts.push("\n=== SCORE BREAKDOWN ===");
      parts.push(`Score: ${job.score != null ? job.score.toFixed(1) : "Not scored"}`);
      parts.push(`Tier: ${job.tier_passed} passed`);
      if (job.score_reasons.length > 0) {
        parts.push("\nReasons:");
        job.score_reasons.forEach(r => parts.push(`  + ${r}`));
      }
      if (job.score_gaps.length > 0) {
        parts.push("\nGaps:");
        job.score_gaps.forEach(g => parts.push(`  - ${g}`));
      }

      // AI Analysis (fetch)
      try {
        const analysis = await api.jobs.analysis.get(job.id);
        parts.push("\n=== AI ANALYSIS ===");
        parts.push(formatAnalysis(analysis));
      } catch {
        parts.push("\n=== AI ANALYSIS ===");
        parts.push("(Not yet analyzed)");
      }

      // Company Research (fetch)
      try {
        const research = await api.jobs.companyResearch.get(job.id);
        parts.push("\n=== COMPANY RESEARCH ===");
        parts.push(formatResearch(research));
      } catch {
        parts.push("\n=== COMPANY RESEARCH ===");
        parts.push("(Not yet researched)");
      }

      // Requirements Summary
      parts.push("\n=== REQUIREMENTS SUMMARY ===");
      parts.push(job.requirements_summary || "(No requirements summary)");
      if (job.technical_tools.length > 0) {
        parts.push(`\nTools: ${job.technical_tools.join(", ")}`);
      }

      // Job Description
      parts.push("\n=== JOB DESCRIPTION ===");
      parts.push(job.jd_full || "(No JD text)");

      // Generated Resumes (fetch list + each detail)
      try {
        const resumeList = await api.resumes.list(job.id);
        if (resumeList.length > 0) {
          for (const r of resumeList) {
            try {
              const detail = await api.resumes.get(r.id);
              parts.push(`\n=== RESUME #${r.id} (${r.provider} / ${r.model}) ===`);
              parts.push(`Generated: ${formatDate(r.generated_at)}`);
              parts.push(`Validation: ${r.validation_passed ? "Passed" : "Failed"}`);
              parts.push("");
              parts.push(detail.resume_text || "(No resume text)");
            } catch {
              parts.push(`\n=== RESUME #${r.id} ===`);
              parts.push("(Failed to load resume text)");
            }
          }
        }
      } catch {
        // No resumes or error fetching — skip silently
      }

      await navigator.clipboard.writeText(parts.join("\n"));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }

  return (
    <Button variant="outline" size="sm" onClick={copyAll} disabled={loading}>
      {loading ? <Loader2 className="animate-spin" /> : copied ? <Check className="text-emerald-600" /> : <Copy />}
      {loading ? "Copying…" : copied ? "Copied!" : "Copy All"}
    </Button>
  );
}
