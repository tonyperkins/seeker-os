"use client";

import { useState, useEffect } from "react";
import { Bookmark, Copy, Check, ExternalLink } from "lucide-react";
import { CollapsibleCard } from "@/components/ui/collapsible-card";
import { Button } from "@/components/ui/button";

export function BookmarkletCard() {
  const [copied, setCopied] = useState(false);
  const [origin, setOrigin] = useState("");
  const [bookmarkletJs, setBookmarkletJs] = useState("");

  useEffect(() => {
    const o = window.location.origin;
    setOrigin(o);
    const target = `${o}/jobs/new`;
    // Bookmarklet that extracts job metadata from the page DOM before navigating
    const js = `javascript:void(function(){` +
      `var t='',c='',l='';` +
      // Try JSON-LD JobPosting schema
      `var ss=document.querySelectorAll('script[type="application/ld+json"]');` +
      `for(var i=0;i<ss.length;i++){try{` +
        `var d=JSON.parse(ss[i].textContent);` +
        `var arr=Array.isArray(d)?d:[d];` +
        `for(var j=0;j<arr.length;j++){` +
          `if(arr[j]['@type']==='JobPosting'){` +
            `t=arr[j].title||'';` +
            `var ho=arr[j].hiringOrganization;` +
            `if(ho)c=ho.name||'';` +
            `var jl=arr[j].jobLocation;` +
            `if(jl&&jl.address)l=(jl.address.addressLocality||'')+(jl.address.addressRegion?(', '+jl.address.addressRegion):'');` +
          `}` +
        `}` +
      `}catch(e){}}` +
      // Fallback: parse document.title ("Title - Company - Location | Site")
      `if(!t){var p=document.title.split(/\\s*[|\\-\\u2013\\u2014]\\s*/).map(function(s){return s.trim()}).filter(Boolean);if(p.length>=2){t=p[0];c=p[1];if(p.length>=3)l=p[2];}}` +
      // Build URL and navigate
      `var u='${target}?url='+encodeURIComponent(window.location.href);` +
      `if(t)u+='&title='+encodeURIComponent(t);` +
      `if(c)u+='&company='+encodeURIComponent(c);` +
      `if(l)u+='&location='+encodeURIComponent(l);` +
      `location.href=u;` +
    `}())`;
    setBookmarkletJs(js);
  }, []);

  const targetUrl = `${origin}/jobs/new`;

  function handleCopy() {
    navigator.clipboard.writeText(bookmarkletJs).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <CollapsibleCard
      icon={Bookmark}
      title="Bookmarklet"
      description="Drag the button to your bookmarks bar. While browsing a job posting, click it to instantly add the job to Seeker OS."
    >
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <a
              href={bookmarkletJs || "#"}
              onClick={(e) => e.preventDefault()}
              className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground cursor-grab"
              title="Drag me to your bookmarks bar"
            >
              <Bookmark className="size-4" />
              Add to Seeker OS
            </a>
            <Button variant="outline" size="sm" onClick={handleCopy} disabled={!origin}>
              {copied ? <Check className="size-3.5 text-emerald-600" /> : <Copy className="size-3.5" />}
              {copied ? "Copied!" : "Copy URL"}
            </Button>
          </div>

          <div className="rounded-md border border-border bg-muted/30 p-3 text-xs text-muted-foreground">
            <p className="font-medium text-foreground mb-1">How it works:</p>
            <ol className="list-decimal list-inside space-y-0.5">
              <li>Drag the &quot;Add to Seeker OS&quot; button to your browser&apos;s bookmarks bar</li>
              <li>Browse any job posting on any site</li>
              <li>Click the bookmarklet — it navigates to Seeker OS with the job URL pre-filled</li>
              <li>Seeker fetches and scores the JD automatically</li>
            </ol>
          </div>

          <div className="rounded-md border border-border p-3">
            <p className="text-xs font-medium text-muted-foreground mb-1">Target URL (auto-detected):</p>
            <p className="text-xs font-mono break-all text-foreground">
              {origin ? targetUrl : "Loading…"}
            </p>
          </div>

          <div className="flex items-start gap-2 text-xs text-muted-foreground">
            <ExternalLink className="mt-0.5 size-3.5 shrink-0" />
            <span>
              The bookmarklet points to <strong>{origin || "this domain"}</strong>. If you deploy Seeker OS to a different domain, revisit this page to get an updated bookmarklet. Works on both HTTP and HTTPS pages.
            </span>
          </div>
        </div>
    </CollapsibleCard>
  );
}
