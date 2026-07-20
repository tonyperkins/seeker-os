# Jordan Rivera

**Cloud & DevOps Engineer — Platform Reliability**

Springfield, IL (Remote) · jordan.rivera@example.com
https://example.com/jordan · https://www.linkedin.com/in/jordanrivera-example
U.S. Citizen — No Sponsorship Required

---

## Professional Summary

Platform and DevOps engineer with a decade of experience building CI/CD pipelines, provisioning cloud infrastructure, and improving incident response across distributed systems.

---

## Core Competencies

| Area | Skills |
|------|--------|
| **AI Infrastructure** | LLM provider routing (Anthropic + OpenAI-compatible) · Local inference (Ollama) · Inference cost optimization |
| **AI Reliability & Quality** | Claim-level accuracy validation · Deterministic/LLM layer separation · Human-in-the-loop policy design |
| **Agentic Systems** | Autonomous ops agent in production · MCP integration · Agent guardrails & failure containment |
| **Cloud Platforms** | AWS (broad familiarity across core services · EC2, S3, IAM, VPC, Lambda, ECS, RDS, CloudWatch) · Azure (production depth, growing) · GCP (delivered production-style platform on Cloud Run — AI-accelerated ramp from zero) |
| **Infrastructure as Code** | Terraform (modular, remote state, CI/CD integration) · CloudFormation |
| **CI/CD & Release Engineering** | GitLab CI · GitHub Actions · Jenkins · Golden paths · Build standardization |
| **Containers & Orchestration** | Kubernetes (production workloads) · Docker · ECS |
| **Observability** | Dynatrace · Datadog · Grafana/Prometheus · Splunk · ELK Stack |
| **Edge & CDN** | Akamai (Bot Manager · Image Manager · Performance) |
| **Security** | IAM · VPC design · Security Groups · Key Vault · SOPS |
| **Programming & Scripting** | Python · Bash · PowerShell · Go (familiar, growing) · C#/.NET · Node.js · Java |
| **SRE Practice** | SLIs/SLOs/Error Budgets · Incident management · Blameless post-mortems · Runbook automation |

<!-- GATED ROWS — add only after corresponding sprint ships:
     - AI Infrastructure: "vLLM" · "LiteLLM"
     - Agentic Systems: "MCP server development" -->

---

## Professional Experience

### Cloud & DevOps Engineer
**Fixture Corp** · Remote · *January 2023 – Present*

- Built and maintained GitLab CI pipelines that automated build and deployment workflows for internal services.
- Built and maintained GitLab CI pipelines that automated build and deployment workflows for client services.
- Built and maintained GitLab CI pipelines that automated build and deployment workflows for partner services.
- Built and maintained GitLab CI pipelines that automated build and deployment workflows for legacy services.
- Implemented Terraform modules to provision multi-region AWS infrastructure, reducing manual provisioning time significantly.
- Led incident response process improvements, cutting mean time to resolution across the platform team.
- *(ClientX)* Migrated legacy Jenkins pipelines to GitHub Actions, reducing CI runtime.
- Established on-call rotation and runbook documentation for platform incidents.
- Presented quarterly infrastructure cost reviews to engineering leadership. <!-- pin -->
- Mentored two junior engineers on Kubernetes deployment patterns and on-call best practices.

---

### Senior Platform Engineer
**Prior Fixture Inc.** · Remote · *June 2019 – December 2022*

- Designed a self-service internal developer platform for provisioning test environments.
- Standardized observability tooling across engineering teams using Prometheus and Grafana.
- Automated database migration workflows, reducing deployment risk.

---

### Systems Engineer
**Old Fixture Systems** · Remote · *March 2010 – May 2015*

- Operated on-premise virtualization infrastructure supporting internal business applications.

---

## Early Career

### Junior Engineer
**Founding Fixture Labs** · Anytown, IL · *February 1998 – August 2003*

Early-career role predating the cloud era; included for continuity of work history.

- Maintained internal tooling for a small engineering team on early web infrastructure.

*The company wound down in 2001 amid the dot-com contraction. The tooling concept was validated by the industry over the following decade.*

---

## Portfolio Projects

### Seeker OS — AI-Powered Job Search Pipeline *(public repo: https://github.com/example/seeker-os)*
*Python/FastAPI · SQLite · multi-provider LLM routing · YAML-driven configuration*

- Config-driven pipeline with deterministic scoring layer firewalled from LLM prompts — reproducible signal can't be contaminated by probabilistic output. <!-- pin -->
- Claim-level accuracy enforcement: every generated resume passes a two-tier validator that cross-checks claims against a source-of-truth master document.

### telemetry-gcp — Azure→GCP Platform Port *(live on Cloud Run · public repo)*
- Ported a production-grade telemetry platform from Azure to GCP in one day, from zero prior GCP experience.
- Diagnosed undocumented upstream IP-range blocking via controlled variable isolation; replaced a $45/mo VPC/NAT stack with a credential-free off-cloud push ingester.

### forge + muster — Agentic Container Hardening with Deterministic Gates *(public repos)*
- forge: autonomous AI agents that analyze and harden container images — 507 → 0 CVEs on a real-world image.
- muster: Go CLI acting as forge's deterministic CI gate — release engineering discipline applied to agentic work.

### Broadlink Manager v2 — Full-Stack Home Assistant Add-on (Python + Vue 3) *(public repo: https://github.com/example/broadlink-manager-v2)*
*Python backend · REST API (documented) · Vue 3 component-based frontend · Docker (HA add-on + standalone) · pytest + Playwright E2E*

- Open-source IR/RF device manager for Home Assistant: Python backend with a documented REST API and a complete Vue 3 component-based frontend.
- Actively maintained with an established user community — 620 commits and 52 releases as of July 2026.

### perkinslab — Self-Hosted Infrastructure & AI Operations Platform
*Proxmox · Docker with GitOps deployment · Ollama local inference · Tailscale · SOPS*

- Autonomous ops agent in production: scheduled jobs, log and email monitoring, and proactive alerting.
- Multi-provider LLM routing with fallback chains and cost-optimized cloud overflow.

### Writing — https://example.com/posts
<!-- List top 2-3 posts here once live, starting with the zero-trust SQL postmortem and the GCP ramp story. -->

---

## Accuracy Notes
*(For resume generation — not included in formatted output)*

This is a synthetic fixture. All names, companies, and claims are invented for testing the master-resume parser and bullet-selection pipeline. It structurally mirrors the real master_resume.md format (heading hierarchy, sub-context annotations, an Early Career section) but contains no real personal data.
