"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Like useState, but persists the value to localStorage so it survives reloads.
 *
 * Initializes with `initial` on both server and first client render to avoid
 * hydration mismatches, then syncs from localStorage in a useEffect after
 * hydration completes.
 *
 * @param key   localStorage key
 * @param initial  default value when nothing is stored (or localStorage is unavailable)
 */
export function usePersistentState<T>(
  key: string,
  initial: T,
  hydrateFromStorage = true,
): [T, (value: T | ((prev: T) => T)) => void] {
  const [state, setState] = useState<T>(initial);

  // Sync from localStorage after hydration (skip when initial came from URL)
  useEffect(() => {
    if (!hydrateFromStorage) return;
    try {
      const stored = localStorage.getItem(key);
      if (stored !== null) {
        const parsed = JSON.parse(stored) as T;
        setState(parsed);
      }
    } catch {
      // ignore parse / access errors
    }
  }, [key, hydrateFromStorage]);

  const update = useCallback(
    (value: T | ((prev: T) => T)) => {
      setState((prev) => {
        const next =
          typeof value === "function" ? (value as (p: T) => T)(prev) : value;
        try {
          localStorage.setItem(key, JSON.stringify(next));
        } catch {
          // ignore quota / access errors
        }
        return next;
      });
    },
    [key],
  );

  return [state, update];
}
