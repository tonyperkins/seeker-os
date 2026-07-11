"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Plus,
  Loader2,
  Play,
  Pencil,
  Check,
  X,
} from "lucide-react";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogClose,
} from "@/components/ui/dialog";
import { api, type QuerySummary } from "@/lib/api";
import { ErrorBanner } from "@/components/error-banner";
import { PageHeader } from "@/components/page-header";
import { DeleteButton } from "@/components/delete-button";

function formatDate(iso: string | null): string {
  if (!iso) return "never";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function QueriesPage() {
  const [queries, setQueries] = useState<QuerySummary[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Add dialog state
  const [addOpen, setAddOpen] = useState(false);
  const [newSlug, setNewSlug] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [newCommitment, setNewCommitment] = useState("full-time");
  const [newMaxPages, setNewMaxPages] = useState("1");
  const [newSearchQuery, setNewSearchQuery] = useState("");
  const [creating, setCreating] = useState(false);

  // Edit state
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editLabel, setEditLabel] = useState("");
  const [editEnabled, setEditEnabled] = useState(true);
  const [editCommitment, setEditCommitment] = useState("full-time");
  const [editMaxPages, setEditMaxPages] = useState("1");
  const [editSearchQuery, setEditSearchQuery] = useState("");
  const [saving, setSaving] = useState(false);

  // Delete state
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [runningId, setRunningId] = useState<number | null>(null);

  const fetchQueries = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.queries.list();
      setQueries(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load queries");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Fetch queries on mount — legitimate data-fetching effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchQueries();
  }, [fetchQueries]);

  async function handleCreate() {
    setCreating(true);
    setError(null);
    try {
      await api.queries.create({
        slug: newSlug.trim(),
        label: newLabel.trim(),
        commitment: newCommitment,
        max_pages: parseInt(newMaxPages, 10) || 1,
        enabled: true,
        search_query: newSearchQuery.trim() || undefined,
      });
      setAddOpen(false);
      setNewSlug("");
      setNewLabel("");
      setNewCommitment("full-time");
      setNewMaxPages("1");
      setNewSearchQuery("");
      await fetchQueries();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create query");
    } finally {
      setCreating(false);
    }
  }

  function startEdit(q: QuerySummary) {
    if (q.id == null) return;
    setEditingId(q.id);
    setEditLabel(q.label);
    setEditEnabled(q.enabled);
    setEditCommitment(q.commitment);
    setEditMaxPages(String(q.max_pages));
    setEditSearchQuery(q.search_query ?? "");
  }

  async function handleSaveEdit() {
    if (editingId == null) return;
    setSaving(true);
    setError(null);
    try {
      await api.queries.update(editingId, {
        label: editLabel.trim(),
        enabled: editEnabled,
        commitment: editCommitment,
        max_pages: parseInt(editMaxPages, 10) || 1,
        search_query: editSearchQuery.trim() || "",
      });
      setEditingId(null);
      await fetchQueries();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update query");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: number) {
    setDeletingId(id);
    setError(null);
    try {
      await api.queries.delete(id);
      setDeletingId(null);
      await fetchQueries();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete query");
      setDeletingId(null);
    }
  }

  async function handleRun(id: number, forceFullPull?: boolean) {
    setRunningId(id);
    setError(null);
    try {
      await api.queries.run(id, forceFullPull);
      await fetchQueries();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run query");
    } finally {
      setRunningId(null);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Queries" actions={
        <Dialog open={addOpen} onOpenChange={setAddOpen}>
          <DialogTrigger render={<Button><Plus /> Add query</Button>} />
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add new query</DialogTitle>
              <DialogDescription>
                Define a hiring.cafe search slug and options.
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="q-slug">Slug</Label>
                <Input
                  id="q-slug"
                  placeholder="e.g. senior-backend"
                  value={newSlug}
                  onChange={(e) => setNewSlug(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="q-label">Label</Label>
                <Input
                  id="q-label"
                  placeholder="e.g. Senior Backend Engineer"
                  value={newLabel}
                  onChange={(e) => setNewLabel(e.target.value)}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="q-commitment">Commitment</Label>
                  <select
                    id="q-commitment"
                    value={newCommitment}
                    onChange={(e) => setNewCommitment(e.target.value)}
                    className="h-8 rounded-lg border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
                  >
                    <option value="full-time" className="bg-background text-foreground">full-time</option>
                    <option value="part-time" className="bg-background text-foreground">part-time</option>
                    <option value="contract" className="bg-background text-foreground">contract</option>
                    <option value="any" className="bg-background text-foreground">any</option>
                  </select>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="q-pages">Max pages</Label>
                  <Input
                    id="q-pages"
                    type="number"
                    min={1}
                    max={10}
                    value={newMaxPages}
                    onChange={(e) => setNewMaxPages(e.target.value)}
                  />
                </div>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="q-search">Search query (optional)</Label>
                <Input
                  id="q-search"
                  placeholder="e.g. senior sre remote"
                  value={newSearchQuery}
                  onChange={(e) => setNewSearchQuery(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  When set, uses structured search with server-side date filtering instead of slug-based URL.
                </p>
              </div>
            </div>
            <DialogFooter>
              <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
              <Button
                disabled={!newSlug.trim() || !newLabel.trim() || creating}
                onClick={handleCreate}
              >
                {creating ? <Loader2 className="animate-spin" /> : <Plus />}
                Create
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      } />

      {error && (
        <ErrorBanner message={error} />
      )}

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
              <Loader2 className="animate-spin" />
              Loading queries…
            </div>
          ) : !queries || queries.length === 0 ? (
            <p className="py-12 text-center text-sm text-muted-foreground">
              No queries configured. Add one to start sourcing jobs.
            </p>
          ) : (
            <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16">On</TableHead>
                  <TableHead>Label</TableHead>
                  <TableHead className="max-w-[20rem]">Slug</TableHead>
                  <TableHead className="w-28">Commitment</TableHead>
                  <TableHead className="w-20">Pages</TableHead>
                  <TableHead className="w-36">Last run</TableHead>
                  <TableHead className="w-48 text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {queries.map((q) => {
                  const isEditing = editingId === q.id;
                  return (
                    <TableRow key={q.id ?? q.slug}>
                      {/* Enable/disable toggle */}
                      <TableCell>
                        {isEditing ? (
                          <Switch
                            checked={editEnabled}
                            onCheckedChange={setEditEnabled}
                          />
                        ) : (
                          <Switch
                            checked={q.enabled}
                            onCheckedChange={(checked) => {
                              if (q.id != null) {
                                api.queries.update(q.id, { enabled: checked }).then(fetchQueries);
                              }
                            }}
                            disabled={q.id == null}
                          />
                        )}
                      </TableCell>
                      {/* Label */}
                      <TableCell>
                        {isEditing ? (
                          <Input
                            value={editLabel}
                            onChange={(e) => setEditLabel(e.target.value)}
                            className="h-7"
                          />
                        ) : (
                          <span className="font-medium">{q.label}</span>
                        )}
                      </TableCell>
                      {/* Slug + search query (2 lines) */}
                      <TableCell className="max-w-[20rem]">
                        <div className="flex flex-col gap-1">
                          <span className="font-mono text-xs truncate">{q.slug}</span>
                          {isEditing ? (
                            <Input
                              value={editSearchQuery}
                              onChange={(e) => setEditSearchQuery(e.target.value)}
                              placeholder="e.g. senior sre remote"
                              className="h-7"
                            />
                          ) : (
                            q.search_query && (
                              <span className="font-mono text-xs text-muted-foreground break-words line-clamp-2">
                                {q.search_query}
                              </span>
                            )
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        {isEditing ? (
                          <select
                            value={editCommitment}
                            onChange={(e) => setEditCommitment(e.target.value)}
                            className="h-7 rounded-md border border-input bg-background px-1.5 text-xs text-foreground outline-none dark:bg-input/30"
                          >
                            <option value="full-time" className="bg-background text-foreground">full-time</option>
                            <option value="part-time" className="bg-background text-foreground">part-time</option>
                            <option value="contract" className="bg-background text-foreground">contract</option>
                            <option value="any" className="bg-background text-foreground">any</option>
                          </select>
                        ) : (
                          <span className="text-muted-foreground">{q.commitment}</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {isEditing ? (
                          <Input
                            type="number"
                            min={1}
                            value={editMaxPages}
                            onChange={(e) => setEditMaxPages(e.target.value)}
                            className="h-7 w-16"
                          />
                        ) : (
                          <span className="text-muted-foreground">{q.max_pages}</span>
                        )}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatDate(q.last_run_at)}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center justify-end gap-1">
                          {isEditing ? (
                            <>
                              <Button
                                size="icon-sm"
                                variant="default"
                                disabled={saving}
                                onClick={handleSaveEdit}
                              >
                                {saving ? <Loader2 className="animate-spin" /> : <Check />}
                              </Button>
                              <Button
                                size="icon-sm"
                                variant="ghost"
                                onClick={() => setEditingId(null)}
                              >
                                <X />
                              </Button>
                            </>
                          ) : (
                            <>
                              <Button
                                size="icon-sm"
                                variant="ghost"
                                disabled={q.id == null || runningId === q.id}
                                onClick={() => q.id != null && handleRun(q.id)}
                                title="Run query (incremental)"
                              >
                                {runningId === q.id ? (
                                  <Loader2 className="animate-spin" />
                                ) : (
                                  <Play />
                                )}
                              </Button>
                              <Button
                                size="icon-sm"
                                variant="ghost"
                                disabled={q.id == null || runningId === q.id}
                                onClick={() => q.id != null && handleRun(q.id, true)}
                                title="Run query (force full pull)"
                                className="text-xs"
                              >
                                <Play className="text-orange-500" />
                                <span className="sr-only">Force full pull</span>
                              </Button>
                              <Button
                                size="icon-sm"
                                variant="ghost"
                                disabled={q.id == null}
                                onClick={() => startEdit(q)}
                                title="Edit"
                              >
                                <Pencil />
                              </Button>
                              <DeleteButton
                                onDelete={async () => {
                                  if (q.id != null) await handleDelete(q.id);
                                }}
                                itemName={`"${q.label}" (${q.slug})`}
                                itemId={q.slug}
                                size="icon-sm"
                                variant="ghost"
                              />
                            </>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
