import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

describe("API proxy redirects", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("preserves an upstream OAuth callback redirect", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, {
      status: 303,
      headers: { Location: "https://seekeros.perkinslab.com/inbound?oauth=connected" },
    })));

    const response = await GET(new NextRequest(
      "https://seekeros.perkinslab.com/api/inbound/oauth/callback?code=example&state=example",
    ));

    expect(response.status).toBe(303);
    expect(response.headers.get("Location")).toBe(
      "https://seekeros.perkinslab.com/inbound?oauth=connected",
    );
  });
});
