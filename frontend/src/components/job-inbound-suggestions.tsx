"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Inbox } from "lucide-react";

import { api, type InboundMessage } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { CollapsibleCard } from "@/components/ui/collapsible-card";

export function JobInboundSuggestions({ jobId }: { jobId: number }) {
  const [messages, setMessages] = useState<InboundMessage[]>([]);

  useEffect(() => {
    api.inbound.list({ state: "matched,unmatched", job_id: jobId })
      .then(setMessages)
      .catch(() => setMessages([]));
  }, [jobId]);

  if (messages.length === 0) return null;
  return (
    <CollapsibleCard
      title="Inbound suggestions"
      description={`${messages.length} email${messages.length === 1 ? "" : "s"} may belong to this application`}
      action={<Link href="/inbound" className="text-xs font-medium text-primary hover:underline">Review all</Link>}
    >
      <div className="flex flex-col gap-2">
        {messages.map((message) => (
          <Link key={message.id} href="/inbound" className="flex items-center gap-3 rounded-md border p-3 hover:bg-muted/50">
            <Inbox className="size-4 text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate text-sm">{message.subject || "(No subject)"}</span>
            <Badge variant="outline">{Math.round(message.match_score * 100)}%</Badge>
          </Link>
        ))}
      </div>
    </CollapsibleCard>
  );
}
