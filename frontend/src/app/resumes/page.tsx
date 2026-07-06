"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2, AlertCircle, FileText, RefreshCw, X } from "lucide-react";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { formatDate } from "@/lib/date";

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

  const fetchResumes = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.resumes.list(jobId ?? undefined);
      setResumes(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load resumes");
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  const handleDelete = useCallback(async (id: number) => {
    await api.resumes.delete(id);
    setResumes((prev) => prev?.filter((r) => r.id !== id) ?? null);
  }, []);

  useEffect(() => {
    // Fetch on mount — legitimate data-fetching effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchResumes();
  }, [fetchResumes]);

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
                No resumes generated yet. Generate one from a job detail page.
              </p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16">ID</TableHead>
                  <TableHead className="w-20">Job ID</TableHead>
                  <TableHead className="min-w-[180px]">Model</TableHead>
                  <TableHead className="w-28">Validation</TableHead>
                  <TableHead className="w-28">Tokens</TableHead>
                  <TableHead className="w-32">Generated</TableHead>
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
                    <TableCell className="font-mono">{resume.job_id}</TableCell>
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
