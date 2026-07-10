import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

describe("Jobs API query contract", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("forwards global sort, pagination, filters, and cancellation", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ jobs: [], total: 0 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await api.jobs.list(
      {
        search: "platform",
        sort_by: "company",
        order: "asc",
        limit: 50,
        offset: 50,
      },
      { signal: controller.signal },
    );

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/jobs?");
    expect(url).toContain("search=platform");
    expect(url).toContain("sort_by=company");
    expect(url).toContain("order=asc");
    expect(url).toContain("limit=50");
    expect(url).toContain("offset=50");
    expect(options.signal).toBe(controller.signal);
  });
});
