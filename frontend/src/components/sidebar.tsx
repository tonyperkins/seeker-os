"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Briefcase, Kanban, Search, FileText, Cpu, Settings, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/theme-toggle";
import { ActivityIndicator } from "@/components/activity-indicator";
import { usePersistentState } from "@/lib/use-persistent-state";

const navItems = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/jobs", label: "Jobs", icon: Briefcase },
  { href: "/kanban", label: "Kanban", icon: Kanban },
  { href: "/queries", label: "Queries", icon: Search },
  { href: "/resumes", label: "Resumes", icon: FileText },
  { href: "/models", label: "Models", icon: Cpu },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = usePersistentState<boolean>("sidebar:collapsed", false);

  // Hide sidebar on onboarding route
  if (pathname === "/onboarding") return null;

  if (collapsed) {
    return (
      <aside className="w-12 border-r border-border bg-sidebar flex flex-col h-screen sticky top-0 shrink-0">
        <div className="flex items-center justify-center p-2 border-b border-border h-14">
          <button
            onClick={() => setCollapsed(false)}
            className="text-muted-foreground hover:text-foreground transition-colors"
            title="Expand sidebar"
          >
            <PanelLeftOpen className="size-5" />
          </button>
        </div>
        <nav className="flex-1 p-1.5 space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
            return (
              <Link
                key={item.href}
                href={item.href}
                title={item.label}
                className={cn(
                  "flex items-center justify-center rounded-md p-2 text-sm font-medium transition-colors",
                  active
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground hover:bg-sidebar-accent/50"
                )}
              >
                <Icon className="h-4 w-4" />
              </Link>
            );
          })}
        </nav>
        <ActivityIndicator />
        <div className="p-1.5 border-t border-border flex justify-center">
          <ThemeToggle />
        </div>
      </aside>
    );
  }

  return (
    <aside className="w-48 border-r border-border bg-sidebar flex flex-col h-screen sticky top-0 shrink-0">
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
      <nav className="flex-1 p-1.5 space-y-0.5">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors",
                active
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground hover:bg-sidebar-accent/50"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <ActivityIndicator />
      <div className="p-1.5 border-t border-border">
        <ThemeToggle />
      </div>
    </aside>
  );
}
