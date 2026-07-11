"use client";

import * as React from "react";
import { ChevronDown } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { useHydrated } from "@/lib/use-persistent-state";

export function CollapsibleCard({
  title,
  description,
  icon: Icon,
  action,
  defaultOpen = false,
  scroll = false,
  contentClassName,
  storageKey,
  className,
  children,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  icon?: React.ComponentType<{ className?: string }>;
  action?: React.ReactNode;
  defaultOpen?: boolean;
  scroll?: boolean;
  contentClassName?: string;
  storageKey?: string;
  className?: string;
  children: React.ReactNode;
}) {
  const [stateOpen, setStateOpen] = React.useState(defaultOpen);
  const hydrated = useHydrated();

  // When storageKey is provided, use localStorage persistence instead of React state.
  // Before hydration, default to open so the server snapshot matches the most common
  // localStorage state (expanded), preventing a flash from collapsed→expanded.
  const persisted = React.useSyncExternalStore(
    (cb) => {
      if (!storageKey) return () => {};
      const handler = (e: StorageEvent) => {
        if (e.key === storageKey || e.key === null) cb();
      };
      window.addEventListener("storage", handler);
      return () => window.removeEventListener("storage", handler);
    },
    () => (storageKey ? localStorage.getItem(storageKey) !== "collapsed" : false),
    () => true,
  );

  const open = storageKey ? (hydrated ? persisted : true) : stateOpen;
  const toggle = () => {
    if (storageKey) {
      const next = !open;
      localStorage.setItem(storageKey, next ? "expanded" : "collapsed");
      window.dispatchEvent(new StorageEvent("storage", { key: storageKey }));
    } else {
      setStateOpen((o) => !o);
    }
  };

  return (
    <Card className={className}>
      <CardHeader
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={toggle}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            toggle();
          }
        }}
        className="flex flex-row items-center justify-between gap-3 cursor-pointer select-none"
      >
        <div className="flex min-w-0 flex-col gap-1">
          <CardTitle className="flex items-center gap-2">
            {Icon && <Icon className="size-5 shrink-0" />}
            {title}
          </CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {action && (
            <div onClick={(e) => e.stopPropagation()}>
              {action}
            </div>
          )}
          <ChevronDown
            className={cn(
              "size-5 shrink-0 text-muted-foreground transition-transform duration-200",
              open && "rotate-180",
            )}
          />
        </div>
      </CardHeader>
      {open && (
        <CardContent
          className={cn(
            scroll && "max-h-[28rem] overflow-y-auto",
            contentClassName,
          )}
        >
          {children}
        </CardContent>
      )}
    </Card>
  );
}
