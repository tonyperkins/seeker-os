"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ExternalLink, Inbox, MailCheck } from "lucide-react";

import { api, type InboundMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/date";
import { Badge } from "@/components/ui/badge";
import { CollapsibleCard } from "@/components/ui/collapsible-card";

function EmailRow({ message, pending = false }: { message: InboundMessage; pending?: boolean }) {
  const detail = (
    <>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{message.subject || "(No subject)"}</span>
        <span className="block truncate text-xs text-muted-foreground">{message.sender_address} · {formatDateTime(message.received_at)}</span>
      </span>
      {pending ? <Badge variant="outline">{Math.round(message.match_score * 100)}%</Badge> : <Badge variant="secondary">Confirmed</Badge>}
    </>
  );

  if (pending) {
    return <Link href="/inbound" className="flex items-center gap-3 rounded-md border p-3 hover:bg-muted/50"><Inbox className="size-4 shrink-0 text-muted-foreground" />{detail}</Link>;
  }
  return (
    <div className="flex items-center gap-3 rounded-md border p-3">
      <MailCheck className="size-4 shrink-0 text-muted-foreground" />
      {detail}
      {message.primary_gmail_link && (
        <a href={message.primary_gmail_link} target="_blank" rel="noreferrer" className="shrink-0 text-muted-foreground hover:text-foreground" aria-label={`Open ${message.subject || "email"} in Gmail`}>
          <ExternalLink className="size-4" />
        </a>
      )}
    </div>
  );
}

export function JobInboundSuggestions({ jobId }: { jobId: number }) {
  const [messages, setMessages] = useState<InboundMessage[]>([]);

  useEffect(() => {
    api.inbound.list({ state: "matched,unmatched,confirmed", job_id: jobId })
      .then(setMessages)
      .catch(() => setMessages([]));
  }, [jobId]);

  const pending = messages.filter((message) => message.state === "matched" || message.state === "unmatched");
  const confirmed = messages.filter((message) => message.state === "confirmed");
  if (messages.length === 0) return null;

  return (
    <CollapsibleCard
      title="Email"
      description={`${confirmed.length} confirmed · ${pending.length} awaiting review`}
      action={pending.length > 0 ? <Link href="/inbound" className="text-xs font-medium text-primary hover:underline">Review inbox</Link> : undefined}
    >
      <div className="flex flex-col gap-4">
        {pending.length > 0 && <section className="flex flex-col gap-2"><p className="text-xs font-medium text-muted-foreground">Awaiting review</p>{pending.map((message) => <EmailRow key={message.id} message={message} pending />)}</section>}
        {confirmed.length > 0 && <section className="flex flex-col gap-2"><p className="text-xs font-medium text-muted-foreground">Confirmed email history</p>{confirmed.map((message) => <EmailRow key={message.id} message={message} />)}</section>}
      </div>
    </CollapsibleCard>
  );
}
