import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useDebouncedValue } from "@/lib/use-debounced-value";

describe("useDebouncedValue", () => {
  afterEach(() => vi.useRealTimers());

  it("publishes only the latest free-text value after the delay", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(
      ({ value }) => useDebouncedValue(value, 300),
      { initialProps: { value: "a" } },
    );

    rerender({ value: "ab" });
    act(() => vi.advanceTimersByTime(200));
    rerender({ value: "abc" });
    act(() => vi.advanceTimersByTime(299));
    expect(result.current).toBe("a");
    act(() => vi.advanceTimersByTime(1));
    expect(result.current).toBe("abc");
  });
});
