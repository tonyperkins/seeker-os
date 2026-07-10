# LLM Observability MVP

**Status:** Implementation  
**Date:** 2026-07-10  
**Area:** Observability

## Goal

Make every LLM invocation in Seeker OS accountable for usage, cost, reliability,
prompt lineage, and quality without copying sensitive prompts or responses into
telemetry. The first complete workflow is tailored-resume generation, including
its deterministic validation and LLM claim-traceability judge.

## Decisions

- SQLite remains the complete local source of truth.
- Telemetry is metadata-only: prompts and completions remain in their existing
  authoritative records, while the ledger stores keyed fingerprints and sizes.
- `ModelRouter.generate()` is the universal instrumentation boundary.
- A logical call is recorded now; physical attempt records wait until retries or
  provider fallback are implemented.
- Resume generation uses an operation ID to correlate generation, validation,
  judge calls, evaluations, and the saved artifact.
- OpenTelemetry/OTLP export is deferred until the local contract is stable.
- Historical artifact rows are not backfilled because they cannot reconstruct
  failures, judge usage, or exact call-time lineage reliably.

## Data Contract

### `llm_calls`

One row represents one logical call, including calls that fail before reaching a
provider. It records:

- `call_id`, optional `operation_id`, and optional `parent_call_id`.
- Task and requested/actual provider and model.
- Route reason, generation parameters, status, stop reason, and normalized error.
- Input/output tokens, latency, call-time prices, estimated cost, and currency.
- Prompt name/version, template digest, rendered prompt HMACs, and byte counts.
- Optional artifact type/ID, timestamps, telemetry schema version, and the fixed
  metadata-only capture level.

Raw prompts, completions, resumes, credentials, headers, and provider exception
bodies are prohibited.

### `llm_evaluations`

One row represents a deterministic or model-based quality result. It records the
operation, subject call, optional judge call, artifact, evaluator identity and
version, metric, label/score/pass result, rubric digest, structured details, and
evaluation time. Claim details include a keyed claim fingerprint, verdict,
fingerprints for the explanation and offending text, and master-resume digest.

Transport, parsing, deterministic validation, and judged quality are separate
outcomes. A valid provider response can therefore have a failed evaluation
without being classified as a transport error.

## Runtime Flow

```text
resume generation operation
├── generation call
├── deterministic accuracy evaluation
├── traceability judge call (child of generation call)
├── per-claim evaluations
└── saved resume artifact linked back to the calls/evaluations
```

Telemetry writes must not mask the original provider result or exception. A
telemetry write failure is logged with a stable event name and contains no model
content.

## User Experience

The observability API and dashboard provide:

- Calls, tokens, and call-time estimated cost by task/provider/model.
- Failure and truncation counts.
- Resume cost including claim validation.
- Deterministic pass rate and unsupported/overstated claim rate.
- Cost per validation-passing resume.
- Recent resume operations with call, evaluation, timing, and artifact detail.

Pre-ledger history is labeled incomplete. Missing telemetry is distinct from a
real zero value.

## Privacy and Retention

Prompt fingerprints use an HMAC key supplied through an environment variable.
When no key is configured, Seeker OS derives an ephemeral process-local key and
marks fingerprints as non-reproducible; startup emits a warning without exposing
the key. Production use should configure `SEEKER_TELEMETRY_HMAC_KEY`.

Metadata retention defaults to 365 days and is configuration-ready, but automatic
deletion is not part of this MVP. Observability endpoints do not expose prompt
fingerprints or unrestricted error/evaluation text.

## Deferred Work

- `llm_operations` and `llm_attempts` tables.
- Application retries and provider fallback accounting.
- Raw or redacted payload archives.
- OpenTelemetry, OTLP, Phoenix, and browser/SSE trace propagation.
- Structured-log conversion, billing reconciliation, SLO alerting, and
  tamper-evident audit manifests.

## Acceptance Criteria

1. Every router outcome creates a call row: routing failure, provider failure,
   empty response, truncation, and success.
2. Resume generation and its judge share an operation ID and parent-child call
   relationship, then link to the saved artifact.
3. Every claim verdict, including supported claims, is queryable as an evaluation.
4. Spend is calculated from immutable call-time rates and includes judge calls.
5. Seeded prompt, resume, PII, and credential canaries never appear in telemetry
   tables, telemetry logs, or observability API responses.
6. Existing databases migrate cleanly, and pre-ledger data is explicitly partial.
7. The full backend test suite and production frontend build pass.
