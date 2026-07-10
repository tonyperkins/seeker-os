import {
  CheckCircle2, XCircle, MinusCircle, Send, CircleDashed,
  Filter, FileSearch, UserX,
} from "lucide-react";

export const STATUS_OPTIONS = [
  { value: "ready", label: "Ready" },
  { value: "reviewing", label: "Reviewing" },
  { value: "interested", label: "Interested" },
  { value: "applied", label: "Applied" },
];

export const SOURCE_OPTIONS = [
  { value: "manual", label: "Manual" },
  { value: "hiring_cafe", label: "hiring.cafe" },
];

export const VERDICT_OPTIONS = [
  { value: "APPLY", label: "Apply", activeClass: "border-border bg-emerald-600 text-white" },
  { value: "CONDITIONAL", label: "Conditional", activeClass: "border-border bg-amber-600 text-white" },
  { value: "MONITOR", label: "Monitor", activeClass: "border-border bg-sky-600 text-white" },
  { value: "SKIP", label: "Skip", activeClass: "border-border bg-red-600 text-white" },
] as const;

export function statusIcon(status: string, isManual?: boolean) {
  const cls = "size-3.5 shrink-0";
  switch (status) {
    case "ready":
    case "interested":
    case "reviewing":
      return <CheckCircle2 className={`${cls} text-emerald-500`} />;
    case "rejected":
      return isManual
        ? <UserX className={`${cls} text-red-700 dark:text-red-400`} />
        : <XCircle className={`${cls} text-red-500`} />;
    case "skipped":
      return <MinusCircle className={`${cls} text-muted-foreground`} />;
    case "applied":
      return <Send className={`${cls} text-violet-500`} />;
    case "discovered":
      return <CircleDashed className={`${cls} text-amber-500`} />;
    case "filtered":
      return <Filter className={`${cls} text-orange-500`} />;
    case "jd_fetched":
      return <FileSearch className={`${cls} text-blue-500`} />;
    default:
      return <CircleDashed className={`${cls} text-muted-foreground/50`} />;
  }
}

export function formatComp(min: number | null, max: number | null): string {
  if (min == null && max == null) return "—";
  const fmt = (n: number) => `$${(n / 1000).toFixed(0)}k`;
  if (min != null && max != null) return `${fmt(min)}–${fmt(max)}`;
  if (min != null) return `${fmt(min)}+`;
  return `≤${fmt(max as number)}`;
}

export function statusRowClass(status: string): string {
  switch (status) {
    case "ready":
      return "bg-emerald-500/5 hover:bg-emerald-500/10";
    case "rejected":
      return "bg-red-500/5 hover:bg-red-500/10";
    case "reviewing":
    case "interested":
      return "bg-sky-500/5 hover:bg-sky-500/10";
    case "applied":
      return "bg-violet-500/5 hover:bg-violet-500/10";
    case "skipped":
      return "bg-muted/40 hover:bg-muted/60";
    case "discovered":
      return "bg-amber-500/5 hover:bg-amber-500/10";
    case "filtered":
      return "bg-orange-500/5 hover:bg-orange-500/10";
    case "jd_fetched":
      return "bg-blue-500/5 hover:bg-blue-500/10";
    default:
      return "";
  }
}
