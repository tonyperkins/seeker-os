"use client";

import { useEffect, useRef } from "react";

/**
 * Warns the user before navigating away (or closing the tab) when `dirty` is true.
 *
 * Usage:
 *   const dirty = formValues !== savedValues;
 *   useDirtyState(dirty);
 */
export function useDirtyState(dirty: boolean) {
  const ref = useRef(dirty);
  ref.current = dirty;

  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (ref.current) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, []);
}
