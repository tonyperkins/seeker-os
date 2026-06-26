"use client";

import { useCallback, useState } from "react";

/**
 * Like useState, but persists the value to localStorage so it survives reloads.
 *
 * Reads synchronously from localStorage during initialization (via lazy
 * useState initializer) so the first render already has the stored value —
 * no flash of default state, no race with effects that depend on the value.
 *
 * @param key   localStorage key
 * @param initial  default value when nothing is stored (or localStorage is unavailable)
 */
export function usePersistentState<T>(
  key: string,
  initial: T,
): [T, (value: T | ((prev: T) => T)) => void] {
  const [state, setState] = useState<T>(() => {
    try {
      const stored = localStorage.getItem(key);
      if (stored !== null) {
        return JSON.parse(stored) as T;
      }
    } catch {
      // ignore parse / access errors
    }
    return initial;
  });

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
