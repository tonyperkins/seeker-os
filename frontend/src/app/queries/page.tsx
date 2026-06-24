"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Plus,
  Loader2,
  AlertCircle,
  Trash2,
  Play,
  Pencil,
  Check,
  X,
} from "lucide-react";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
  const [creating, setCreating] = useState(false);

  // Edit state
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editLabel, setEditLabel] = useState("");
  const [editEnabled, setEditEnabled] = useState(true);
  const [editCommitment, setEditCommitment] = useState("full-time");
  const [editMaxPages, setEditMaxPages] = useState("1");
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
      });
      setAddOpen(false);
      setNewSlug("");
      setNewLabel("");
      setNewCommitment("full-time");
      setNewMaxPages("1");
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

  async function handleRun(id: number) {
    setRunningId(id);
    setError(null);
    try {
      await api.queries.run(id);
      await fetchQueries();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run query");
    } finally {
      setRunningId(null);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Queries</h1>
          <p className="text-sm text-muted-foreground">
            Search query definitions sourced from hiring.cafe.
          </p>
        </div>
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
                    className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
                  >
                    <option value="full-time">full-time</option>
                    <option value="part-time">part-time</option>
                    <option value="contract">contract</option>
                    <option value="any">any</option>
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
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          <AlertCircle className="size-4 shrink-0" />
          {error}
        </div>
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
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Slug</TableHead>
                  <TableHead>Label</TableHead>
                  <TableHead className="w-28">Commitment</TableHead>
                  <TableHead className="w-20">Pages</TableHead>
                  <TableHead className="w-24">Enabled</TableHead>
                  <TableHead className="w-36">Last run</TableHead>
                  <TableHead className="w-48 text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {queries.map((q) => {
                  const isEditing = editingId === q.id;
                  return (
                    <TableRow key={q.id ?? q.slug}>
                      <TableCell className="font-mono text-xs">{q.slug}</TableCell>
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
                      <TableCell>
                        {isEditing ? (
                          <select
                            value={editCommitment}
                            onChange={(e) => setEditCommitment(e.target.value)}
                            className="h-7 rounded-md border border-input bg-transparent px-1.5 text-xs outline-none dark:bg-input/30"
                          >
                            <option value="full-time">full-time</option>
                            <option value="part-time">part-time</option>
                            <option value="contract">contract</option>
                            <option value="any">any</option>
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
                      <TableCell>
                        {isEditing ? (
                          <label className="flex items-center gap-1.5 text-xs">
                            <input
                              type="checkbox"
                              checked={editEnabled}
                              onChange={(e) => setEditEnabled(e.target.checked)}
                              className="size-3.5"
                            />
                            {editEnabled ? "on" : "off"}
                          </label>
                        ) : (
                          <Badge variant={q.enabled ? "default" : "outline"}>
                            {q.enabled ? "enabled" : "disabled"}
                          </Badge>
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
                                title="Run query"
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
                                disabled={q.id == null}
                                onClick={() => startEdit(q)}
                                title="Edit"
                              >
                                <Pencil />
                              </Button>
                              <Dialog>
                                <DialogTrigger
                                  render={
                                    <Button
                                      size="icon-sm"
                                      variant="ghost"
                                      disabled={q.id == null}
                                      title="Delete"
                                    >
                                      <Trash2 className="text-destructive" />
                                    </Button>
                                  }
                                />
                                <DialogContent>
                                  <DialogHeader>
                                    <DialogTitle>Delete query?</DialogTitle>
                                    <DialogDescription>
                                      Remove &ldquo;{q.label}&rdquo; ({q.slug}). This cannot be undone.
                                    </DialogDescription>
                                  </DialogHeader>
                                  <DialogFooter>
                                    <DialogClose render={<Button variant="outline" />}>
                                      Cancel
                                    </DialogClose>
                                    <Button
                                      variant="destructive"
                                      disabled={q.id == null || deletingId === q.id}
                                      onClick={() => q.id != null && handleDelete(q.id)}
                                    >
                                      {deletingId === q.id ? (
                                        <Loader2 className="animate-spin" />
                                      ) : (
                                        <Trash2 />
                                      )}
                                      Delete
                                    </Button>
                                  </DialogFooter>
                                </DialogContent>
                              </Dialog>
                            </>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
