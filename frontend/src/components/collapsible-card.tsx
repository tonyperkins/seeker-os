"use client";

import { useSyncExternalStore, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardAction,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface CollapsibleCardProps {
  title: ReactNode;
  description?: string;
  storageKey: string;
  action?: ReactNode;
  className?: string;
  contentClassName?: string;
  children: ReactNode;
}

export function CollapsibleCard({
  title,
  description,
  storageKey,
  action,
  className,
  contentClassName,
  children,
}: CollapsibleCardProps) {
  const collapsed = useSyncExternalStore(
    (cb) => {
      const handler = (e: StorageEvent) => {
        if (e.key === storageKey || e.key === null) cb();
      };
      window.addEventListener("storage", handler);
      return () => window.removeEventListener("storage", handler);
    },
    () => localStorage.getItem(storageKey) === "collapsed",
    () => false,
  );

  const toggle = () => {
    const next = !collapsed;
    localStorage.setItem(storageKey, next ? "collapsed" : "expanded");
    window.dispatchEvent(new StorageEvent("storage", { key: storageKey }));
  };

  return (
    <Card className={className}>
      <CardHeader>
        <button
          onClick={toggle}
          className="flex items-start gap-2 text-left cursor-pointer"
        >
          <ChevronDown
            className={cn(
              "size-4 shrink-0 mt-0.5 text-muted-foreground transition-transform",
              collapsed && "-rotate-90"
            )}
          />
          <div className="flex flex-col gap-0.5">
            <CardTitle>{title}</CardTitle>
            {description && <CardDescription>{description}</CardDescription>}
          </div>
        </button>
        {action && <CardAction>{action}</CardAction>}
      </CardHeader>
      {!collapsed && (
        <CardContent className={contentClassName}>
          {children}
        </CardContent>
      )}
    </Card>
  );
}
