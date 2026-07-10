"use client";

import { useState, useCallback } from "react";
import { api } from "@/lib/api";

export interface BulkSelection {
  scope: string;
  ids: Set<number>;
}

export interface BulkProgress {
  current: number;
  total: number;
  action: string;
}

export interface UseBulkActionsResult {
  selection: BulkSelection;
  selectedIds: Set<number>;
  bulkLoading: boolean;
  bulkError: string | null;
  bulkProgress: BulkProgress | null;
  toggleJob: (id: number, scope: string) => void;
  toggleAll: (ids: number[], scope: string) => void;
  allSelected: (ids: number[], scope: string) => boolean;
  someSelected: boolean;
  clearSelection: (scope: string) => void;
  runBulkAction: (action: string, fn: (id: number) => Promise<unknown>, refetch: () => void) => Promise<void>;
}

export function useBulkActions(): UseBulkActionsResult {
  const [selection, setSelection] = useState<BulkSelection>({ scope: "", ids: new Set() });
  const [bulkLoading, setBulkLoading] = useState(false);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [bulkProgress, setBulkProgress] = useState<BulkProgress | null>(null);

  const getScopedIds = useCallback((scope: string): Set<number> => {
    return selection.scope === scope ? selection.ids : new Set<number>();
  }, [selection]);

  const toggleJob = useCallback((id: number, scope: string) => {
    setSelection((previous) => {
      const next = new Set(previous.scope === scope ? previous.ids : []);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return { scope, ids: next };
    });
  }, []);

  const toggleAll = useCallback((ids: number[], scope: string) => {
    const current = getScopedIds(scope);
    if (ids.length > 0 && current.size === ids.length && ids.every((id) => current.has(id))) {
      setSelection({ scope, ids: new Set() });
    } else {
      setSelection({ scope, ids: new Set(ids) });
    }
  }, [getScopedIds]);

  const allSelected = useCallback((ids: number[], scope: string): boolean => {
    const current = getScopedIds(scope);
    return ids.length > 0 && ids.every((id) => current.has(id));
  }, [getScopedIds]);

  const clearSelection = useCallback((scope: string) => {
    setSelection({ scope, ids: new Set() });
  }, []);

  const runBulkAction = useCallback(async (
    action: string,
    fn: (id: number) => Promise<unknown>,
    refetch: () => void,
  ) => {
    setBulkLoading(true);
    setBulkError(null);
    const ids = [...selection.ids];
    const errors: string[] = [];
    for (let i = 0; i < ids.length; i++) {
      setBulkProgress({ current: i + 1, total: ids.length, action });
      try {
        await fn(ids[i]);
      } catch (err) {
        errors.push(`Job ${ids[i]}: ${err instanceof Error ? err.message : "failed"}`);
      }
    }
    setBulkLoading(false);
    setBulkProgress(null);
    setSelection({ scope: selection.scope, ids: new Set() });
    if (errors.length > 0) {
      setBulkError(`${action}: ${errors.length}/${ids.length} failed — ${errors.slice(0, 3).join("; ")}${errors.length > 3 ? "…" : ""}`);
    } else {
      setBulkError(null);
    }
    refetch();
  }, [selection]);

  return {
    selection,
    selectedIds: selection.ids,
    bulkLoading,
    bulkError,
    bulkProgress,
    toggleJob,
    toggleAll,
    allSelected,
    someSelected: selection.ids.size > 0,
    clearSelection,
    runBulkAction,
  };
}
