"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  Loader2, AlertCircle, FileText, RefreshCw, X, ExternalLink,
  ArrowUpDown, ArrowUp, ArrowDown, Search,
} from "lucide-react";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DeleteButton } from "@/components/delete-button";
import { CopyResumeButton } from "@/components/copy-resume-button";
import { api, type ResumeSummary } from "@/lib/api";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { formatDate } from "@/lib/date";

type ResumeSortKey = "id" | "job_company" | "provider" | "model" | "tokens" | "latency_ms" | "generated_at";

export default function ResumesPage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center py-12 text-sm text-muted-foreground">Loading…</div>}>
      <ResumesContent />
    </Suspense>
  );
}

function ResumesContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const jobIdParam = searchParams.get("job_id");
  const jobId = jobIdParam ? Number(jobIdParam) : null;
  const [resumes, setResumes] = useState<ResumeSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<ResumeSortKey>("generated_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const debouncedSearch = useDebouncedValue(search, 300);

  const fetchResumes = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.resumes.list({
        jobId: jobId ?? undefined,
        search: debouncedSearch.trim() || undefined,
        sort_by: sortKey,
        order: sortDir,
      });
      setResumes(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load resumes");
    } finally {
      setLoading(false);
    }
  }, [jobId, debouncedSearch, sortKey, sortDir]);

  const handleDelete = useCallback(async (id: number) => {
    await api.resumes.delete(id);
    setResumes((prev) => prev?.filter((r) => r.id !== id) ?? null);
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchResumes();
  }, [fetchResumes]);

  function toggleSort(key: ResumeSortKey) {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  function sortIcon(key: ResumeSortKey) {
    if (sortKey !== key) return <ArrowUpDown className="size-3 text-muted-foreground/50" />;
    return sortDir === "asc" ? <ArrowUp className="size-3 text-primary" /> : <ArrowDown className="size-3 text-primary" />;
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Resumes</h1>
          {jobId && (
            <div className="mt-2 flex items-center gap-2">
              <Badge variant="secondary">Filtered by job #{jobId}</Badge>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => router.push("/resumes")}
                className="h-6 px-2 text-xs"
              >
                <X className="size-3" /> Clear
              </Button>
            </div>
          )}
        </div>
        <Button variant="outline" size="sm" onClick={fetchResumes} disabled={loading}>
          {loading ? <Loader2 className="animate-spin" /> : <RefreshCw />}
          Refresh
        </Button>
      </div>

      <div className="flex items-center gap-2">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="text"
            placeholder="Search company, provider, model…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8 pr-8"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X className="size-4" />
            </button>
          )}
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          {error ? (
            <div className="flex items-center gap-2 p-6 text-sm text-destructive">
              <AlertCircle className="size-4 shrink-0" />
              {error}
            </div>
          ) : loading ? (
            <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
              <Loader2 className="animate-spin" />
              Loading resumes…
            </div>
          ) : !resumes || resumes.length === 0 ? (
            <div className="flex flex-col items-center gap-3 py-16 text-center">
              <FileText className="size-10 text-muted-foreground/50" />
              <p className="text-sm text-muted-foreground">
                No resumes{search ? " match your search" : " generated yet"}. {search ? "Try clearing the search." : "Generate one from a job detail page."}
              </p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16" aria-sort={sortKey === "id" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}>
                    <button type="button" onClick={() => toggleSort("id")} className="flex items-center gap-1 hover:text-foreground">
                      ID {sortIcon("id")}
                    </button>
                  </TableHead>
                  <TableHead className="w-20">Job ID</TableHead>
                  <TableHead className="min-w-[120px]" aria-sort={sortKey === "job_company" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}>
                    <button type="button" onClick={() => toggleSort("job_company")} className="flex items-center gap-1 hover:text-foreground">
                      Company {sortIcon("job_company")}
                    </button>
                  </TableHead>
                  <TableHead className="min-w-[180px]" aria-sort={sortKey === "model" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}>
                    <button type="button" onClick={() => toggleSort("model")} className="flex items-center gap-1 hover:text-foreground">
                      Model {sortIcon("model")}
                    </button>
                  </TableHead>
                  <TableHead className="w-28">Validation</TableHead>
                  <TableHead className="w-28" aria-sort={sortKey === "tokens" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}>
                    <button type="button" onClick={() => toggleSort("tokens")} className="flex items-center gap-1 hover:text-foreground">
                      Tokens {sortIcon("tokens")}
                    </button>
                  </TableHead>
                  <TableHead className="w-24">Cost</TableHead>
                  <TableHead className="w-32" aria-sort={sortKey === "generated_at" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}>
                    <button type="button" onClick={() => toggleSort("generated_at")} className="flex items-center gap-1 hover:text-foreground">
                      Generated {sortIcon("generated_at")}
                    </button>
                  </TableHead>
                  <TableHead className="w-12" />
                  <TableHead className="w-12" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {resumes.map((resume) => (
                  <TableRow
                    key={resume.id}
                    className="cursor-pointer"
                    onClick={() => router.push(`/resumes/${resume.id}`)}
                  >
                    <TableCell className="font-mono font-medium">
                      {resume.id}
                    </TableCell>
                    <TableCell className="font-mono">
                      <Link
                        href={`/jobs/${resume.job_id}`}
                        onClick={(e) => e.stopPropagation()}
                        className="inline-flex items-center gap-1 text-primary hover:underline"
                      >
                        {resume.job_id}
                        <ExternalLink className="size-3" />
                      </Link>
                    </TableCell>
                    <TableCell className="text-sm">
                      {resume.job_company || "—"}
                    </TableCell>
                    <TableCell className="text-sm">
                      <span className="font-medium">{resume.provider}</span>
                      <span className="text-muted-foreground"> / {resume.model}</span>
                    </TableCell>
                    <TableCell>
                      {resume.validation_passed ? (
                        <Badge variant="default" className="bg-emerald-600 text-white">
                          ✓ Passed
                        </Badge>
                      ) : (
                        <Badge variant="destructive">
                          ✗ Failed
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="font-mono text-sm">
                      {(resume.input_tokens + resume.output_tokens).toLocaleString()}
                    </TableCell>
                    <TableCell className="font-mono text-sm text-muted-foreground">
                      {resume.estimated_cost != null
                        ? `$${resume.estimated_cost.toFixed(4)}`
                        : "—"}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatDate(resume.generated_at)}
                    </TableCell>
                    <TableCell>
                      <CopyResumeButton resumeId={resume.id} />
                    </TableCell>
                    <TableCell>
                      <DeleteButton
                        itemName={`resume #${resume.id}`}
                        itemId={resume.id}
                        onDelete={() => handleDelete(resume.id)}
                        size="icon"
                        variant="ghost"
                        triggerClassName="h-8 w-8 p-0 text-muted-foreground hover:text-destructive"
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
