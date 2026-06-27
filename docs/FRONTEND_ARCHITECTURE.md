# Seeker OS — Frontend Architecture

**Last updated:** 2026-06-27
**Framework:** Next.js (App Router) + Tailwind CSS + shadcn/ui
**Location:** `frontend/src/`

---

## Page Map

```
frontend/src/app/
├── layout.tsx              Root layout — sidebar, theme toggle, global styles
├── page.tsx                Dashboard — funnel stats, recent runs, top matches, setup status
├── onboarding/
│   └── page.tsx            Onboarding wizard — LLM provider setup, resume upload, config review
├── jobs/
│   ├── page.tsx            Jobs list — filterable table with score badges and status
│   └── [id]/
│       └── page.tsx        Job detail — metadata, analysis, research, resume gen, events, actions
├── kanban/
│   └── page.tsx            Kanban board — drag-and-drop status columns
├── queries/
│   └── page.tsx            Query management — CRUD + run individual queries
├── resumes/
│   ├── page.tsx            Resume list — all generated resumes with filters
│   └── [id]/
│       └── page.tsx        Resume detail — text, validation, download, inline editor
├── models/
│   └── page.tsx            LLM models — providers, tiers, tasks, OAuth, test/fetch
└── settings/
    └── page.tsx            Settings — profile, filters, accuracy rules, company research, backup
```

---

## Component Inventory

### Layout & Navigation

| Component | File | Description |
|---|---|---|
| `Sidebar` | `components/sidebar.tsx` | Collapsible nav — Dashboard, Jobs, Kanban, Queries, Resumes, Models, Settings. Theme toggle. Hidden on `/onboarding`. |
| `ThemeToggle` | `components/theme-toggle.tsx` | Dark/light mode toggle with system preference detection. |

### Job-Related

| Component | File | Description |
|---|---|---|
| `AddJobDialog` | `components/add-job-dialog.tsx` | Manual job entry dialog — URL, title, company, JD text. Handles duplicate detection. |
| `JobActions` | `components/job-actions.tsx` | Job action buttons — reject, skip, override, apply, transition, clean-start, delete. |
| `JobAnalysis` | `components/job-analysis.tsx` | JD analysis display — verdict, gaps, rubric breakdown, run/re-run analysis. |
| `CompanyResearch` | `components/company-research.tsx` | Company research display — dossier, funding, sentiment, fit, run/re-run research. |
| `EventTimeline` | `components/event-timeline.tsx` | Append-only event timeline — chronological list with actor badges and metadata. |
| `GenerateResumeButton` | `components/generate-resume-button.tsx` | Resume generation trigger with task selection and SSE progress streaming. |
| `ScoreBadges` | `components/score-badges.tsx` | Score display — base score, research-adjusted, net score with color coding. |
| `AIPolicyToggle` | `components/ai-policy-toggle.tsx` | Per-job AI policy selector (allowed / draft_only / forbidden). |
| `FilterForm` | `components/filter-form.tsx` | Job list filters — status, score, tier, company, source. |
| `JdRenderer` | `components/jd-renderer.tsx` | Job description text renderer. |
| `RunPipelineButton` | `components/run-pipeline-button.tsx` | Pipeline run trigger with SSE progress and results display. |
| `RunAllButton` | `components/run-all-button.tsx` | Run all queries button. |

### Resume-Related

| Component | File | Description |
|---|---|---|
| `ResumeEditor` | `components/resume-editor.tsx` | Inline resume text editor with save. |
| `CopyResumeButton` | `components/copy-resume-button.tsx` | Copy resume text to clipboard. |
| `CopyAllButton` | `components/copy-all-button.tsx` | Copy all resume text with formatting. |
| `CopyButton` | `components/copy-button.tsx` | Generic copy-to-clipboard button. |
| `DeleteResumeButton` | `components/delete-resume-button.tsx` | Delete resume with confirmation. |
| `ClearExportsButton` | `components/clear-exports-button.tsx` | Clear cached PDF/DOCX exports. |
| `RevalidateButton` | `components/revalidate-button.tsx` | Re-run accuracy validation on a resume. |
| `DraftBanner` | `components/draft-banner.tsx` | Draft notice banner for `draft_only` AI policy. |
| `MasterResumeUpload` | `components/master-resume-upload.tsx` | Master resume file upload (md, docx, pdf). |

### Settings-Related

| Component | File | Description |
|---|---|---|
| `SettingsClient` | `components/settings-client.tsx` | Settings page client component — orchestrates profile, filters, config cards. |
| `ProfileForm` | `components/profile-form.tsx` | Profile configuration form — role, location, comp, experience. |
| `AccuracyRulesCard` | `components/accuracy-rules-card.tsx` | Accuracy rules editor — add/remove/edit rules, AI-generate from description. |
| `CompanyResearchSettingsCard` | `components/company-research-settings-card.tsx` | Company research settings — Tavily config, API key, test connection, advanced settings. |
| `SettingsConfigCard` | `components/settings-config-card.tsx` | Read-only config display — scoring rubric, sources. |
| `BackupRestoreCard` | `components/backup-restore-card.tsx` | Backup/restore — download config zip, restore, download DB, restore DB. |
| `EditProviderDialog` | `components/edit-provider-dialog.tsx` | LLM provider edit dialog — API key, base URL, enabled toggle. |
| `AnthropicAuthDialog` | `components/anthropic-auth-dialog.tsx` | Anthropic OAuth flow dialog — initiate, paste code, status display. |

### Onboarding

| Component | File | Description |
|---|---|---|
| `SetupGuide` | `components/setup-guide.tsx` | Onboarding/setup checklist — shows setup completion status on dashboard. |

### UI Primitives (shadcn/ui)

| Component | File |
|---|---|
| `Badge` | `components/ui/badge.tsx` |
| `Button` | `components/ui/button.tsx` |
| `Card` | `components/ui/card.tsx` |
| `CollapsibleCard` | `components/ui/collapsible-card.tsx` |
| `Dialog` | `components/ui/dialog.tsx` |
| `DropdownMenu` | `components/ui/dropdown-menu.tsx` |
| `Input` | `components/ui/input.tsx` |
| `Label` | `components/ui/label.tsx` |
| `Progress` | `components/ui/progress.tsx` |
| `ScrollArea` | `components/ui/scroll-area.tsx` |
| `Select` | `components/ui/select.tsx` |
| `Separator` | `components/ui/separator.tsx` |
| `Table` | `components/ui/table.tsx` |
| `Tabs` | `components/ui/tabs.tsx` |
| `Textarea` | `components/ui/textarea.tsx` |

---

## API Client

**File:** `frontend/src/lib/api.ts`

Single exported `api` object with nested namespaces for each backend router. All API
calls go through `fetchAPI<T>()` which handles JSON serialization, error parsing, and
FormData (for file uploads).

### API Base URL Resolution

```
SSR (server-side):  process.env.SERVER_API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
CSR (client-side):  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
```

In Docker, `SERVER_API_URL` is set to the backend container's internal address for SSR,
while `NEXT_PUBLIC_API_URL` is the host-mapped port for browser requests.

### API Namespaces

| Namespace | Methods |
|---|---|
| `api.jobs` | `list`, `get`, `create`, `update`, `override`, `reject`, `skip`, `apply`, `delete`, `transition`, `logEngagedEvent`, `cleanStart`, `crossRef`, `companyResearch.get/run`, `analysis.get/run` |
| `api.pipeline` | `run`, `runTier`, `runs`, `getRun`, `runStream` |
| `api.queries` | `list`, `create`, `update`, `delete`, `run` |
| `api.settings` | `get` |
| `api.analytics` | `funnel` |
| `api.resumes` | `list`, `get`, `update`, `delete`, `generate`, `generateStream`, `validate`, `clearExports`, `pdfUrl`, `markdownUrl`, `docxUrl`, `getMaster`, `uploadMaster`, `parse` |
| `api.profile` | `get` (`/api/profile`), `update` (`/api/profile`) |
| `api.filters` | `get` (`/api/filters`), `update` (`/api/filters`) |
| `api.accuracyRules` | `get` (`/api/accuracy-rules`), `update`, `aiGenerate` |
| `api.models` | `getConfig`, `fetch`, `test`, `testAll`, `updateProvider`, `updateTier`, `updateTask`, `oauthInitiate`, `oauthCallback`, `oauthStatus` |
| `api.companyResearchSettings` | `get`, `update`, `testConnection` |
| `api.backup` | `download`, `restore`, `downloadDB`, `restoreDB` |
| `api.health` | Health check |
| `api.logs` | Backend log lines |

### SSE Streaming

`runStream` and `generateStream` return `{ response, controller }` where `controller`
is an `AbortController` for cancellation. The caller reads the `ReadableStream` from
the `Response` and parses SSE events.

---

## State Management

### Persistent State

**Hook:** `frontend/src/lib/use-persistent-state.ts` → `usePersistentState<T>(key, default)`

Stores UI state in `localStorage` with a namespaced key. Used for:
- Sidebar collapsed state (`sidebar:collapsed`)
- Job list filters (`jobs:filter:status`, `jobs:filter:minScore`, etc.)

### Server State

No React Query or SWP. Pages fetch data directly via the `api` object during render
(server-side) or in `useEffect` (client-side). Some pages use server components for
initial data loading and pass data as props to client components.

---

## Styling

- **Tailwind CSS** — utility-first, configured with CSS variables for theming
- **shadcn/ui** — component primitives built on Radix UI, styled with Tailwind
- **Dark mode** — CSS variable-based, toggled by `ThemeToggle` component
- **Global styles** — `frontend/src/app/globals.css` defines CSS variables for both themes

---

## Routing

Next.js App Router (file-based routing):

| Route | Page |
|---|---|
| `/` | Dashboard |
| `/onboarding` | Onboarding wizard |
| `/jobs` | Jobs list |
| `/jobs/[id]` | Job detail |
| `/kanban` | Kanban board |
| `/queries` | Query management |
| `/resumes` | Resume list |
| `/resumes/[id]` | Resume detail |
| `/models` | LLM models & providers |
| `/settings` | Settings |

The sidebar is hidden on `/onboarding` to provide a focused setup experience.
