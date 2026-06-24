"use client";

import { useMemo } from "react";

/**
 * Detects whether the JD text is HTML or plain text and renders accordingly.
 * HTML is sanitized via a basic tag allowlist (no scripts, no inline event handlers).
 * Plain text is rendered with whitespace preservation.
 */
export function JDRenderer({ content }: { content: string }) {
  const isHtml = useMemo(() => {
    if (!content) return false;
    // Check for common HTML tags
    const htmlIndicators = /<(div|p|br|ul|ol|li|span|strong|em|a|table|tr|td|th|h[1-6])\b/i;
    return htmlIndicators.test(content);
  }, [content]);

  if (!content) {
    return <p className="text-sm text-muted-foreground">No JD text available.</p>;
  }

  if (isHtml) {
    // Basic sanitization: strip script tags and event handlers
    const sanitized = content
      .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, "")
      .replace(/\son\w+\s*=\s*"[^"]*"/gi, "")
      .replace(/\son\w+\s*=\s*'[^']*'/gi, "")
      .replace(/javascript:/gi, "");

    return (
      <div
        className="jd-html text-sm leading-relaxed [&_a]:text-primary [&_a]:underline [&_h1]:text-lg [&_h1]:font-semibold [&_h1]:mt-4 [&_h1]:mb-2 [&_h2]:text-base [&_h2]:font-semibold [&_h2]:mt-3 [&_h2]:mb-1.5 [&_h3]:font-semibold [&_h3]:mt-2 [&_h3]:mb-1 [&_p]:mb-3 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:mb-3 [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:mb-3 [&_li]:mb-1 [&_strong]:font-semibold [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-border [&_td]:p-1.5 [&_th]:border [&_th]:border-border [&_th]:p-1.5 [&_th]:font-semibold [&_br]:block"
        dangerouslySetInnerHTML={{ __html: sanitized }}
      />
    );
  }

  return (
    <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">
      {content}
    </pre>
  );
}
