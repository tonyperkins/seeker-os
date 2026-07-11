"use client";

import { X } from "lucide-react";
import { usePersistentState } from "@/lib/use-persistent-state";
import { cn } from "@/lib/utils";

interface DismissibleBannerProps {
  /** Unique ID for this banner — used to persist the dismissed state. */
  noticeId: string;
  /** Content to render inside the banner. */
  children: React.ReactNode;
  /** Tailwind classes for the banner styling (border, bg, text color). */
  className?: string;
}

/**
 * An amber/info banner that can be dismissed by the user.
 * The dismissed state is persisted to localStorage via usePersistentState,
 * so it stays dismissed across page reloads.
 */
export function DismissibleBanner({ noticeId, children, className }: DismissibleBannerProps) {
  const [dismissed, setDismissed] = usePersistentState<boolean>(
    `notice:dismissed:${noticeId}`,
    false,
  );

  if (dismissed) return null;

  return (
    <div
      className={cn(
        "flex items-start gap-2 rounded-md border px-3 py-2 text-sm",
        className,
      )}
    >
      <div className="flex-1">{children}</div>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        className="shrink-0 text-muted-foreground/60 transition-colors hover:text-foreground"
        aria-label="Dismiss notice"
      >
        <X className="size-4" />
      </button>
    </div>
  );
}
