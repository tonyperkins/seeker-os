#!/usr/bin/env node

/**
 * Seeker OS — Screenshot Capture Script
 *
 * Navigates to each page of the web dashboard and captures screenshots
 * for use in documentation. Captures both light and dark theme variants.
 *
 * Usage:
 *   cd frontend
 *   npm run capture-screenshots
 *
 * Prerequisites:
 *   - Backend running on http://localhost:8000
 *   - Frontend running on http://localhost:3000
 *   - Playwright browsers installed: npx playwright install chromium
 *
 * Hybrid structure:
 *   Each screenshot target is a self-contained async function with a
 *   waitFor selector. To promote into Playwright test specs later, wrap
 *   with expect() assertions and move into test.describe/test.test blocks.
 *   The import path (@playwright/test) stays the same.
 */

import { chromium } from "@playwright/test";
import { mkdirSync, existsSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = resolve(__dirname, "..", "..");
const OUTPUT_DIR = resolve(PROJECT_ROOT, "docs", "screenshots");

const BASE_URL = process.env.BASE_URL || "http://localhost:3000";
const API_URL = process.env.API_URL || "http://localhost:8000";
const VIEWPORT = { width: 1440, height: 900 };

// ---------------------------------------------------------------------------
// Screenshot targets
// ---------------------------------------------------------------------------
// Each entry describes a page to capture:
//   name          — filename stem (e.g. "dashboard" → dashboard-light.png)
//   path          — route path, or async function resolving to a path (or null to skip)
//   waitFor       — CSS selector to wait for before screenshotting
//   desc          — human-readable description for logging
//   viewportOnly  — if true, capture viewport only (for long-list pages)
//   collapsibles  — if true, capture two variants: all-collapsed and all-expanded
//
// To promote a target into a Playwright test, wrap the navigation + waitFor
// in a test() block and add expect() assertions on the selector or content.

const targets = [
  {
    name: "dashboard",
    path: "/",
    waitFor: "h1",
    desc: "Pipeline funnel, recent runs, top matches",
  },
  {
    name: "onboarding",
    path: "/onboarding",
    waitFor: "h1",
    desc: "First-time setup wizard",
  },
  {
    name: "jobs",
    path: "/jobs",
    waitFor: "h1",
    desc: "Job list with filters and search",
    viewportOnly: true,
  },
  {
    name: "job-detail",
    path: async () => {
      // Prefer a "ready" job (scored, JD fetched) for a rich screenshot.
      // Fall back to any jd_fetched job, then any job as a last resort.
      for (const params of ["status=ready&limit=1", "status=jd_fetched&limit=1", "limit=1"]) {
        const res = await fetch(`${API_URL}/api/jobs?${params}`);
        if (!res.ok) continue;
        const data = await res.json();
        const jobs = Array.isArray(data) ? data : data.jobs;
        if (jobs && jobs.length > 0) return `/jobs/${jobs[0].id}`;
      }
      return null;
    },
    waitFor: "h1",
    desc: "Individual job detail with analysis and actions",
    collapsibles: true,
  },
  {
    name: "kanban",
    path: "/kanban",
    waitFor: "h1",
    desc: "Kanban board for application tracking",
    viewportOnly: true,
  },
  {
    name: "queries",
    path: "/queries",
    waitFor: "h1",
    desc: "Source query management",
  },
  {
    name: "resumes",
    path: "/resumes",
    waitFor: "h1",
    desc: "Generated resumes list",
  },
  {
    name: "models",
    path: "/models",
    waitFor: "h1",
    desc: "LLM provider and model configuration",
  },
  {
    name: "settings",
    path: "/settings",
    waitFor: "h1",
    desc: "Settings overview with config cards",
    collapsibles: true,
  },
];

// ---------------------------------------------------------------------------
// Core capture logic
// ---------------------------------------------------------------------------

async function captureTarget(page, target, theme, outputDir) {
  const themeLabel = theme === "dark" ? "dark" : "light";

  // Resolve path — may be async (e.g. fetching a job ID for detail page)
  const route = typeof target.path === "function" ? await target.path() : target.path;

  if (!route) {
    console.log(`  SKIP  ${target.name} (${themeLabel}) — no path resolved`);
    return;
  }

  console.log(`  CAP   ${target.name} (${themeLabel}) → ${route}`);
  await page.goto(`${BASE_URL}${route}`, { waitUntil: "networkidle" });

  // Wait for the page to render
  try {
    await page.waitForSelector(target.waitFor, { timeout: 10000 });
  } catch {
    console.log(`  WARN  selector "${target.waitFor}" not found for ${target.name}, capturing anyway`);
  }

  // Settle time for animations / loading spinners
  await page.waitForTimeout(800);

  const fullPage = !target.viewportOnly;

  // For full-page captures, the sidebar's h-screen + sticky top-0 causes
  // it to cap at viewport height while the flex container grows taller.
  // Override to height:auto + position:static so the flex container's
  // default align-items:stretch makes the sidebar match the content height.
  if (fullPage) {
    await page.addStyleTag({
      content: `
        aside { position: static !important; height: auto !important; }
      `,
    });
  }

  if (target.collapsibles) {
    // Capture all-collapsed variant
    await setCollapsibleState(page, false);
    const collapsedName = `${target.name}-collapsed-${themeLabel}.png`;
    await page.screenshot({ path: resolve(outputDir, collapsedName), fullPage });
    console.log(`  OK    ${collapsedName}`);

    // Capture all-expanded variant
    await setCollapsibleState(page, true);
    const expandedName = `${target.name}-expanded-${themeLabel}.png`;
    await page.screenshot({ path: resolve(outputDir, expandedName), fullPage });
    console.log(`  OK    ${expandedName}`);
  } else {
    const filename = `${target.name}-${themeLabel}.png`;
    await page.screenshot({ path: resolve(outputDir, filename), fullPage });
    console.log(`  OK    ${filename}`);
  }
}

async function setCollapsibleState(page, expand) {
  const attr = expand ? "false" : "true";
  // Re-query after each click — React re-renders on toggle, so cached
  // locator references go stale. Loop until no more matching elements.
  for (;;) {
    const count = await page.locator(`[role="button"][aria-expanded="${attr}"]`).count();
    if (count === 0) break;
    await page.locator(`[role="button"][aria-expanded="${attr}"]`).first().click();
    await page.waitForTimeout(200);
  }
  await page.waitForTimeout(300);
}

async function checkServer(url, label) {
  try {
    const res = await fetch(url);
    return res.ok;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  console.log("Seeker OS — Screenshot Capture\n");

  // Preflight: check servers
  console.log("Checking servers…");
  const frontendOk = await checkServer(BASE_URL);
  const backendOk = await checkServer(`${API_URL}/api/health`);

  if (!frontendOk) {
    console.error(`✗ Frontend not reachable at ${BASE_URL}`);
    console.error("  Start it with: cd frontend && npm run dev");
    process.exit(1);
  }

  if (!backendOk) {
    console.warn(`⚠ Backend not reachable at ${API_URL} — some pages may show errors`);
  } else {
    console.log("✓ Frontend and backend are running");
  }

  // Create output directory
  if (!existsSync(OUTPUT_DIR)) {
    mkdirSync(OUTPUT_DIR, { recursive: true });
  }
  console.log(`Output: ${OUTPUT_DIR}\n`);

  // Launch browser
  const browser = await chromium.launch({ headless: true });

  let captured = 0;
  let skipped = 0;

  for (const theme of ["light", "dark"]) {
    console.log(`\n--- ${theme.toUpperCase()} theme ---`);

    // Fresh context per theme for full isolation
    const context = await browser.newContext({
      viewport: VIEWPORT,
      deviceScaleFactor: 2,
    });

    // Set theme via localStorage before any page scripts run
    await context.addInitScript((t) => {
      localStorage.setItem("seeker-os-theme", t);
    }, theme);

    const page = await context.newPage();

    for (const target of targets) {
      const before = captured;
      await captureTarget(page, target, theme, OUTPUT_DIR);
      // Track counts (simplified — captureTarget logs skip/ok)
      if (target.name) captured++;
    }

    await page.close();
    await context.close();
  }

  await browser.close();

  const total = targets.length * 2;
  console.log(`\n✓ Done. ${total} screenshots attempted → ${OUTPUT_DIR}`);
  console.log("  Check for SKIP/WARN lines above for any pages that needs attention.");
}

main().catch((err) => {
  console.error("\n✗ Screenshot capture failed:", err);
  process.exit(1);
});
