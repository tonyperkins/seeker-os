import { Badge } from "@/components/ui/badge";

const VERDICT_STYLES: Record<string, { className: string; label: string }> = {
  APPLY: { className: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/30", label: "APPLY" },
  CONDITIONAL: { className: "bg-amber-500/15 text-amber-700 dark:text-amber-400 border-amber-500/30", label: "CONDITIONAL" },
  MONITOR: { className: "bg-sky-500/15 text-sky-700 dark:text-sky-400 border-sky-500/30", label: "MONITOR" },
  SKIP: { className: "bg-red-500/15 text-red-700 dark:text-red-400 border-red-500/30", label: "SKIP" },
};

export function VerdictBadge({ verdict, hasAnalysis }: { verdict: string | null; hasAnalysis: boolean }) {
  if (!hasAnalysis || !verdict) {
    return (
      <Badge variant="outline" className="text-muted-foreground border-muted-foreground/20 bg-muted/30">
        not analyzed
      </Badge>
    );
  }
  const style = VERDICT_STYLES[verdict] ?? VERDICT_STYLES.SKIP;
  return (
    <Badge variant="outline" className={style.className}>
      {style.label}
    </Badge>
  );
}
