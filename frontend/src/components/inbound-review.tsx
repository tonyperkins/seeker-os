"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Check, ExternalLink, Inbox, Loader2, Mail, RefreshCw, ShieldAlert, X } from "lucide-react";

import { api, type InboundMessage, type InboundStatus, type JobSummary } from "@/lib/api";
import { formatDateTime } from "@/lib/date";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

function scoreLabel(score: number): string {
  return `${Math.round(score * 100)}%`;
}

export function InboundReview() {
  const [status, setStatus] = useState<InboundStatus | null>(null);
  const [messages, setMessages] = useState<InboundMessage[]>([]);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [selectedJobs, setSelectedJobs] = useState<Record<number, number>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [nextStatus, nextMessages, active] = await Promise.all([
        api.inbound.status(),
        api.inbound.list({ state: "matched,unmatched" }),
        api.jobs.list({ status: "applied,engaged", sort_by: "company", limit: 500 }),
      ]);
      setStatus(nextStatus);
      setMessages(nextMessages);
      setJobs(active.jobs);
      setSelectedJobs(Object.fromEntries(
        nextMessages
          .filter((message) => message.suggested_job_id !== null)
          .map((message) => [message.id, message.suggested_job_id as number]),
      ));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load inbound review");
    }
  }, []);

  useEffect(() => {
    // Defer the first fetch so React does not treat its state updates as a
    // synchronous effect cascade.
    void Promise.resolve().then(load);
  }, [load]);

  const jobsById = useMemo(
    () => new Map(jobs.map((job) => [job.id, job])),
    [jobs],
  );

  async function checkNow() {
    setBusy("check");
    setError(null);
    try {
      const result = await api.inbound.check();
      setNotice(
        result.resynced
          ? `Recovered the Gmail cursor and added ${result.messages_inserted} message(s).`
          : `Checked Gmail and added ${result.messages_inserted} new message(s).`,
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gmail check failed");
    } finally {
      setBusy(null);
    }
  }

  async function connect() {
    setBusy("oauth");
    setError(null);
    try {
      const result = await api.inbound.startOAuth();
      window.location.assign(result.authorization_url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start Gmail authorization");
      setBusy(null);
    }
  }

  async function decide(message: InboundMessage, action: "confirm" | "dismiss") {
    setBusy(`${action}-${message.id}`);
    setError(null);
    try {
      if (action === "confirm") {
        const jobId = selectedJobs[message.id];
        if (!jobId) throw new Error("Choose an application before confirming");
        await api.inbound.confirm(message.id, jobId);
      } else {
        await api.inbound.dismiss(message.id);
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Decision failed");
    } finally {
      setBusy(null);
    }
  }

  if (error && !status) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Inbound is not ready</CardTitle>
          <CardDescription>{error}</CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          Copy <code>config/email.example.yml</code> to <code>config/email.yml</code>, add the two mailbox addresses, and enable the integration.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {error && <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</div>}
      {notice && <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-800 dark:text-emerald-200">{notice}</div>}

      <Card>
        <CardHeader className="border-b">
          <div>
            <CardTitle className="flex items-center gap-2"><Inbox className="size-4" /> Dedicated Gmail</CardTitle>
            <CardDescription>
              {status?.dedicated_account_address ?? "Loading configuration…"} · read-only access
            </CardDescription>
          </div>
          <div data-slot="card-action" className="flex items-center gap-2">
            {!status?.oauth.connected && (
              <Button onClick={connect} disabled={busy !== null}>
                {busy === "oauth" ? <Loader2 className="animate-spin" /> : <Mail />}
                Connect Gmail
              </Button>
            )}
            <Button variant="outline" onClick={checkNow} disabled={busy !== null || !status?.oauth.connected}>
              {busy === "check" ? <Loader2 className="animate-spin" /> : <RefreshCw />}
              Check now
            </Button>
          </div>
        </CardHeader>
        <CardContent className="grid gap-3 pt-1 sm:grid-cols-3">
          <div><p className="text-xs text-muted-foreground">Connection</p><p className="font-medium">{status?.oauth.connected ? status.oauth.account_email : "Not connected"}</p></div>
          <div><p className="text-xs text-muted-foreground">Last successful check</p><p className="font-medium">{formatDateTime(status?.last_success_at ?? null)}</p></div>
          <div><p className="text-xs text-muted-foreground">Waiting for review</p><p className="font-medium">{status?.pending_count ?? messages.length}</p></div>
          {status?.last_error && <p className="sm:col-span-3 text-sm text-destructive">Last error: {status.last_error}</p>}
        </CardContent>
      </Card>

      {status && !status.message_id_equality_verified && (
        <div className="flex gap-3 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-900 dark:text-amber-200">
          <ShieldAlert className="mt-0.5 size-4 shrink-0" />
          <p>Primary-mailbox links are disabled. First send a message through the Cloudflare Email Worker and verify that both Gmail copies expose the exact same RFC Message-ID; then set <code>message_id_equality_verified: true</code>.</p>
        </div>
      )}

      {messages.length === 0 ? (
        <Card><CardContent className="py-10 text-center text-muted-foreground">No messages need review.</CardContent></Card>
      ) : messages.map((message) => (
        <Card key={message.id}>
          <CardHeader className="border-b">
            <div className="min-w-0">
              <CardTitle className="truncate">{message.subject || "(No subject)"}</CardTitle>
              <CardDescription>{message.sender_address} · {formatDateTime(message.received_at)}</CardDescription>
            </div>
            <Badge data-slot="card-action" variant={message.state === "matched" ? "default" : "outline"}>
              {message.state === "matched" ? `Matched ${scoreLabel(message.match_score)}` : "Unmatched"}
            </Badge>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <Select
                value={selectedJobs[message.id] ? String(selectedJobs[message.id]) : ""}
                onValueChange={(value) => value && setSelectedJobs((current) => ({ ...current, [message.id]: Number(value) }))}
              >
                <SelectTrigger className="min-w-72"><SelectValue placeholder="Choose an active application" /></SelectTrigger>
                <SelectContent>
                  {jobs.map((job) => <SelectItem key={job.id} value={String(job.id)}>{job.company} — {job.title}</SelectItem>)}
                </SelectContent>
              </Select>
              <Button onClick={() => decide(message, "confirm")} disabled={busy !== null || !selectedJobs[message.id]}>
                {busy === `confirm-${message.id}` ? <Loader2 className="animate-spin" /> : <Check />}
                Confirm
              </Button>
              <Button variant="ghost" onClick={() => decide(message, "dismiss")} disabled={busy !== null}>
                {busy === `dismiss-${message.id}` ? <Loader2 className="animate-spin" /> : <X />}
                Dismiss
              </Button>
              {message.primary_gmail_link && (
                <a
                  className={buttonVariants({ variant: "outline" })}
                  href={message.primary_gmail_link}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open in primary Gmail <ExternalLink />
                </a>
              )}
            </div>
            {message.match_candidates.length > 0 && (
              <div className="text-xs text-muted-foreground">
                Ranked evidence: {message.match_candidates.slice(0, 5).map((candidate) => {
                  const job = jobsById.get(candidate.job_id);
                  return <span key={candidate.job_id} className="mr-3"><Link className="underline hover:text-foreground" href={`/jobs/${candidate.job_id}`}>{job ? `${job.company} — ${job.title}` : `Job #${candidate.job_id}`}</Link> {scoreLabel(candidate.score)}</span>;
                })}
              </div>
            )}
            {message.state === "unmatched" && (
              <p className="text-xs text-muted-foreground">Google account and security mail is expected here. Leave it unmatched and dismiss it; it is not a sync error.</p>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
