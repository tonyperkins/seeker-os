"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { LayoutDashboard, Briefcase, Kanban, Search, FileText, Cpu, Settings, PanelLeftClose, PanelLeftOpen, Menu, X, Activity } from "lucide-react";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/theme-toggle";
import { ActivityIndicator } from "@/components/activity-indicator";
import { usePersistentState, useHydrated } from "@/lib/use-persistent-state";

const navItems = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/jobs", label: "Jobs", icon: Briefcase },
  { href: "/kanban", label: "Kanban", icon: Kanban },
  { href: "/queries", label: "Queries", icon: Search },
  { href: "/resumes", label: "Resumes", icon: FileText },
  { href: "/models", label: "Models", icon: Cpu },
  { href: "/observability", label: "Observability", icon: Activity },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();
  const hydrated = useHydrated();
  const [collapsed, setCollapsed] = usePersistentState<boolean>("sidebar:collapsed", false);
  const [mobileOpen, setMobileOpen] = useState(false);

  if (pathname === "/onboarding") return null;

  const isActive = (href: string) =>
    pathname === href || (href !== "/" && pathname.startsWith(href));

  const navContent = (iconOnly: boolean) => (
    <nav className="flex-1 p-1.5 space-y-0.5">
      {navItems.map((item) => {
        const Icon = item.icon;
        const active = isActive(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            title={iconOnly ? item.label : undefined}
            onClick={() => setMobileOpen(false)}
            className={cn(
              "flex items-center rounded-md text-sm font-medium transition-colors",
              iconOnly ? "justify-center p-2" : "gap-2.5 px-2.5 py-1.5",
              active
                ? "bg-sidebar-accent text-sidebar-accent-foreground"
                : "text-sidebar-foreground hover:bg-sidebar-accent/50"
            )}
          >
            <Icon className="h-4 w-4 shrink-0" />
            {!iconOnly && item.label}
          </Link>
        );
      })}
    </nav>
  );

  return (
    <>
      {/* Mobile top bar */}
      <div className="md:hidden sticky top-0 z-50 flex items-center justify-between h-14 px-4 border-b border-border bg-sidebar shrink-0">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setMobileOpen(true)}
            className="text-muted-foreground hover:text-foreground transition-colors"
            title="Open menu"
          >
            <Menu className="size-5" />
          </button>
          <h1 className="text-base font-bold tracking-tight">Seeker OS</h1>
        </div>
        <ThemeToggle />
      </div>

      {/* Mobile slide-over */}
      {mobileOpen && (
        <div className="md:hidden fixed inset-0 z-50">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setMobileOpen(false)}
          />
          <aside className="absolute left-0 top-0 h-full w-64 border-r border-border bg-sidebar flex flex-col">
            <div className="flex items-center justify-between p-3 border-b border-border h-14">
              <div>
                <h1 className="text-base font-bold tracking-tight">Seeker OS</h1>
                <p className="text-[10px] text-muted-foreground">Job Search Pipeline</p>
              </div>
              <button
                onClick={() => setMobileOpen(false)}
                className="text-muted-foreground hover:text-foreground transition-colors"
                title="Close menu"
              >
                <X className="size-5" />
              </button>
            </div>
            {navContent(false)}
            <ActivityIndicator />
          </aside>
        </div>
      )}

      {/* Desktop sidebar — suppressed until hydrated to avoid flash */}
      {hydrated && collapsed && (
        <aside className="hidden md:flex w-12 border-r border-border bg-sidebar flex-col h-screen sticky top-0 shrink-0">
          <div className="flex items-center justify-center p-2 border-b border-border h-14">
            <button
              onClick={() => setCollapsed(false)}
              className="text-muted-foreground hover:text-foreground transition-colors"
              title="Expand sidebar"
            >
              <PanelLeftOpen className="size-5" />
            </button>
          </div>
          {navContent(true)}
          <ActivityIndicator />
          <div className="p-1.5 border-t border-border flex justify-center">
            <ThemeToggle />
          </div>
        </aside>
      )}

      {/* Desktop expanded */}
      {hydrated && !collapsed && (
        <aside className="hidden md:flex w-48 border-r border-border bg-sidebar flex-col h-screen sticky top-0 shrink-0">
          <div className="flex items-center justify-between p-3 border-b border-border h-14">
            <div>
              <h1 className="text-base font-bold tracking-tight">Seeker OS</h1>
              <p className="text-[10px] text-muted-foreground">Job Search Pipeline</p>
            </div>
            <button
              onClick={() => setCollapsed(true)}
              className="text-muted-foreground hover:text-foreground transition-colors"
              title="Collapse sidebar"
            >
              <PanelLeftClose className="size-4" />
            </button>
          </div>
          {navContent(false)}
          <ActivityIndicator />
          <div className="p-1.5 border-t border-border">
            <ThemeToggle />
          </div>
        </aside>
      )}
    </>
  );
}
