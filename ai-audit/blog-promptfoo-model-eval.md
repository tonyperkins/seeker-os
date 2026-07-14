# The Quest for the Right LLM: A Promptfoo Story in Four Acts

> How I benchmarked 19 models across 48 test cases to find the best LLM for each job in my job-hunt tool — and what I learned about reasoning models, judge bias, and the price of accuracy.

---

## Act I: The Budget Brawl

I built a tool called SeekerOS. It scrapes job boards, scores postings against my resume, runs an LLM to produce a verdict (APPLY / CONDITIONAL / MONITOR / SKIP), and generates a tailored resume for the ones worth applying to. The pipeline makes four LLM calls per job: company research, JD analysis, resume generation, and a traceability check that verifies every claim in the generated resume traces back to my master resume.

The problem: I didn't know which model to use for each task. I was routing everything through a Kilo Gateway aggregator with whatever model I'd last configured, hoping for the best.

I decided to fix this properly. I'd heard about promptfoo — an evaluation framework that runs your prompts against a dataset of test cases and gives you pass/fail results. It supports LLM-as-judge for subjective grading, Python assertions for objective checks, and YAML configs that make it easy to swap models.

First I needed a golden dataset. I exported 34 JD analysis cases from my scan history — jobs where I'd already made an apply/skip decision that agreed with the LLM's verdict. Each case has the JD text, the expected verdict, and metadata. For resume generation, I filtered to 14 APPLY/CONDITIONAL cases (you don't generate resumes for SKIP jobs).

Then I wrote the promptfoo configs. JD analysis was straightforward: run the model, parse the JSON, check if the verdict matches. No judge needed — it's a pure assertion. Resume generation was harder: I needed an LLM judge that reads the generated resume alongside my master resume and flags any unsupported or overstated claims. Any fabricated metric, any embellished skill, any invented technology = fail.

I pointed it at Kilo Gateway and let it rip across their budget models: deepseek-v4-flash, GLM-5.2, Qwen, Tencent Hy3, Poolside Laguna, Minimax. Thirteen models on a 6-test quick screen, then the top performers on the full 34+14 dataset.

The results were... sobering.

DeepSeek v4 Flash and GLM-5.2 tied at 61.8% on JD analysis. Not great, but the failures had a pattern: both models confused SKIP with CONDITIONAL. They'd upgrade borderline-reject jobs to "maybe review this." Annoying but safe — you review a job you should've skipped, no harm done. The dangerous failure (CONDITIONAL → APPLY, applying to a bad fit) showed up 3 times in deepseek and once in GLM.

Resume generation was worse. GLM-5.2 led the pack at 71.4%. DeepSeek scored 42.9%. Every model fabricated metrics, overstated experience, or invented technologies. One model claimed I had "deep hands-on experience with Terraform, AWS, Kubernetes, and CI/CD systems" — my resume says "broad familiarity" with AWS. Another invented Apache NiFi out of whole cloth. A third claimed I "built" engineering teams when my resume says I led them.

The free model (Tencent Hy3) scored 57.1% at $0.00. The "pro" model (DeepSeek v4 Pro, discounted tier) scored 28.6% — worse than its cheaper "flash" sibling. Reasoning tokens were a double-edged sword: models that spent 85% of their completion tokens on internal thinking didn't produce better output. They just thought about it longer before making the same mistakes.

I had numbers. I had a leaderboard. But I also had a nagging feeling that 61.8% wasn't good enough for something that writes resumes I'm going to send to real companies.

---

## Act II: The Judge Broke, Then I Broke the Judge

Before I could test frontier models, I had to fix the eval infrastructure. The judge was broken in three ways I discovered sequentially, each more frustrating than the last.

**Problem 1: The judge couldn't see the master resume.** Promptfoo's `llm-rubric` assertion only passes the model's output to the judge — not the original input prompt. So the judge was evaluating resume claims in a vacuum, with no master resume to check against. Every resume passed because the judge had no reference. I fixed this by embedding the master resume text directly in the rubric value. Obvious in hindsight.

**Problem 2: Reasoning models eat all the tokens.** I tried using a reasoning model as the judge. It spent 99% of its completion tokens on internal thinking and produced 30-75 visible tokens of output. The JSON verdict was either truncated or missing entirely. I bumped max_tokens from 4096 to 16000. Still not enough — the model would think for 15,000 tokens and emit a two-sentence verdict. I switched to `minimax/minimax-m3`, a non-reasoning model that reliably produces visible JSON output. Problem solved.

**Problem 3: Models prepend "Thinking:" before their JSON.** Qwen and several other reasoning models output their internal reasoning as visible text before the JSON payload. The JSON parser would choke on "Thinking: I need to evaluate this job..." and fail the test. I wrote a robust extraction function that scans backwards from the end of the output for the first valid JSON object. This caught the edge cases but also made the eval more permissive than production — a gap I noted as tech debt for later.

With the judge fixed, I extended the script to support direct API calls to OpenAI, Anthropic, and Grok — not just Kilo Gateway. Each provider has different auth, different base URLs, different model naming. I wrote a case statement in `compare_models.sh` that handles the routing, rewrites the promptfoo YAML configs on the fly, and sets the right judge model per provider.

Then I pointed it at OpenAI.

---

## Act III: The Frontier Arrives

I ran three OpenAI models on "medium effort" with the full dataset: gpt-5.6-sol (the expensive one), gpt-5.6-terra (the mid-tier), and gpt-5.6-luna (the cheapest).

gpt-5.6-terra scored 82.4% on JD analysis and 100% on resume generation. Eighty-two point four percent. After seeing budget models stuck at 61.8%, terra jumped 20 points. And 100% on resume generation — zero unsupported claims, zero fabricated metrics, zero invented technologies across all 14 test cases.

gpt-5.6-luna, the cheapest of the three, also scored 100% on resume generation and 67.6% on JD analysis. gpt-5.6-sol, the most expensive, underperformed both — 64.7% JD and 85.7% resume. More money doesn't buy better results. Sol had 7 API errors from rate limiting, which probably dragged its score down, but even adjusting for that, it wasn't better than terra.

The frontier models' JD analysis failures were mostly the safe kind: SKIP → CONDITIONAL and APPLY → CONDITIONAL. They over-review, they don't under-review. Terra had zero false positives. Luna had one — a single CONDITIONAL → APPLY. That's the failure mode I can live with.

Then I ran Anthropic. Claude Sonnet 5 scored 70.6% on JD analysis and 100% on resume generation — joining terra and luna in the 100% resume club. Claude Haiku 4.5 scored 92.9% on resume generation at a fraction of the cost, but tanked on JD analysis at 38.2% — worse than every budget model. Haiku is too aggressive: 11 of its 21 JD failures were false positives, recommending APPLY for jobs that should be SKIP or CONDITIONAL. Not suitable for analysis. Its properties — non-reasoning, fast, cheap, reliable JSON — make it a natural judge candidate, though I haven't yet measured its judge accuracy directly.

Sonnet 5 had an interesting failure pattern: it was too conservative, downgrading CONDITIONAL jobs to SKIP. The opposite of GPT models, which upgrade SKIP to CONDITIONAL. Same net effect (safe failure) but from the other direction.

The frontier models had won. But I still didn't have a budget option I felt good about — and I wanted to know if any non-frontier model could close the gap.

---

## Act IV: The Non-Frontier Surprise

I wasn't done. The frontier models were clear winners, but I wanted to know if any non-frontier model could close the gap at budget prices. I tested nine more models through Kilo Gateway: Mistral Medium 3.1, Mistral Large 2512, Kimi K2, Kimi K2 Thinking, Cohere Command A, Meta Llama 4 Maverick, and the three Gemini variants (Pro, 3.5 Flash, 2.5 Flash).

The results were surprising.

**Mistral Large 2512 scored 76.5% on JD analysis** — second only to terra (82.4%), beating Sonnet-5 (70.6%) and Luna (67.6%). At $0.39 per eval run, it ties gpt-5.6-sol ($5.91) at 1/15th the cost. Only 1 false positive. Zero parse failures. This is the model that changed my hybrid config.

**Kimi K2 scored 73.5% on JD analysis** at $0.41 — third-best non-frontier, with the safest budget failure pattern I've seen (1 false positive, dominant failure is SKIP→CONDITIONAL over-review).

**Gemini was a disaster across all three tiers.** Gemini Pro scored 60.4% combined at $3.55 — worse than GLM-5.2 ($2.67). Gemini 3.5 Flash had 11 false positives on 13 JD failures — the most dangerous model tested. Gemini 2.5 Flash scored 50.0% combined, barely above Llama 4 Maverick (47.9%). Priced like frontier models, performed like budget models.

**Reasoning tokens are a net negative.** I tested Kimi K2 Thinking (the reasoning variant) against regular Kimi K2. The thinking version scored lower on both tasks (62.5% vs 68.8% combined), cost more ($1.03 vs $0.59), took twice as long (36m vs 18m), and had 6 parse failures from reasoning text prepended to JSON output. This confirmed the pattern across all reasoning models I tested: they think longer, cost more, and produce worse results for instruction-following tasks.

**Cohere Command A was overpriced and underperformed** — 56.2% combined at $1.86, worse than deepseek ($0.21). Its structured-output reputation didn't translate.

**Llama 4 Maverick was the cheapest ($0.13) and worst (47.9%).** Zero false positives — it never said APPLY when it shouldn't — but it also rarely said APPLY when it should. 14 of 18 failures were SKIP→CONDITIONAL. Not useful as a filter when it flags everything for review.

---

## The Verdict

Here's the complete leaderboard — all 16 models that ran the full 34+14 dataset, sorted by combined accuracy:

| Model | JD Analysis | Resume Gen | Combined | Eval Cost |
|-------|-------------|------------|----------|----------|
| gpt-5.6-terra | 82.4% | 100% | 87.5% | $3.02 |
| claude-sonnet-5 | 70.6% | 100% | 79.2% | $5.95 |
| gpt-5.6-luna | 67.6% | 100% | 77.1% | $1.31 |
| mistralai/mistral-large-2512 | 76.5% | 57.1% | 70.8% | $0.39 |
| gpt-5.6-sol | 64.7% | 85.7% | 70.8% | $5.91 |
| moonshotai/kimi-k2 | 73.5% | 57.1% | 68.8% | $0.59 |
| GLM-5.2 | 61.8% | 71.4% | 64.6% | $2.67 |
| moonshotai/kimi-k2-thinking | 70.6% | 42.9% | 62.5% | $1.03 |
| ~google/gemini-pro-latest | 64.7% | 50.0% | 60.4% | $3.55 |
| google/gemini-3.5-flash | 61.8% | 57.1% | 60.4% | $1.50 |
| mistralai/mistral-medium-3.1 | 67.6% | 42.9% | 60.4% | $0.44 |
| deepseek-v4-flash | 61.8% | 42.9% | 56.2% | $0.21 |
| cohere/command-a | 61.8% | 42.9% | 56.2% | $1.86 |
| claude-haiku-4.5 | 38.2% | 92.9% | 54.2% | $0.26 |
| google/gemini-2.5-flash | 50.0% | 50.0% | 50.0% | $0.85 |
| meta-llama/llama-4-maverick | 47.1% | 50.0% | 47.9% | $0.13 |

> Eval Cost = total token cost of running both eval configs (34 JD tests + 14 resume tests) for that model. Not per-job production cost. Three additional models (Tencent Hy3:free, Poolside Laguna, DeepSeek v4 Pro:discounted) ran resume generation only and are omitted from this table.

The cost analysis is where it gets interesting. My pipeline makes 4 LLM calls per job. At gpt-5.6-terra for everything, that's $0.155 per job. At deepseek-v4-flash, it's $0.014. But I don't have to use the same model for everything.

The recommended hybrid: deepseek for company research ($0.002), Mistral Large 2512 for JD analysis ($0.004), gpt-5.6-luna for resume generation ($0.011), claude-haiku for the traceability judge ($0.009). Total: ~$0.026 per job. That's 6x cheaper than all-terra while maintaining 100% resume accuracy. JD analysis at 76.5% — only 6 points behind terra, with just 1 false positive.

At 100 jobs per week, the hybrid costs $2.60. The all-terra approach costs $15.50. For a personal project, that's the difference between "I can run this every day" and "I should think twice before scanning."

---

## What I Learned

**The 6-test screen lies.** Three models scored 83.3% on the 6-test screen. DeepSeek v4 Flash dropped to 61.8% on the full 34. The small sample over-represents easy cases. Always run the full dataset before making decisions.

**Reasoning tokens don't correlate with accuracy.** Models that think longer don't produce better output. DeepSeek Pro scored worse than DeepSeek Flash. GLM spent ~85% of its completion tokens on reasoning and still fabricated claims. Kimi K2 Thinking scored lower than regular Kimi K2 on both tasks. The frontier models that scored 100% on resume generation aren't reasoning models — they're just better at following instructions.

**More expensive doesn't mean better.** gpt-5.6-sol costs 2x more than terra and scored lower. DeepSeek Pro costs more than Flash and scored lower. Gemini Pro costs 9x more than Mistral Large and scored lower. Price is a proxy for compute, not for quality on your specific task.

**Judge selection is critical.** A reasoning model as judge produces "..." and fails silently. A non-reasoning model produces clean JSON. The judge needs to see the reference material (master resume) — if it can't, every test passes and you learn nothing.

**Failure patterns matter more than accuracy numbers.** 61.8% with all safe failures (SKIP → CONDITIONAL) is better than 70% with dangerous failures (CONDITIONAL → APPLY). Look at the confusion matrix, not just the pass rate.

**Promptfoo is a pre-deployment gate, not a runtime cost.** The eval cost $0-6 per model to run the full dataset. In production, that same $6 covers 38 jobs with terra or 428 jobs with deepseek. You run promptfoo when something changes — model, prompt, rules, resume — not on every job.

The infrastructure is in place. The findings are documented. The CI workflow is locked to manual-only because I'm not paying for automated evals on a personal project. When I'm ready to test Grok, the script supports it — I just need API keys and a willingness to spend more than any model tested so far.

The known open item: validating Haiku's accuracy as a traceability judge. Its 92.9% resume generation score proves it understands the content — but judge accuracy is a different skill that requires its own eval. That's the next test on the backlog.

For now, the hybrid configuration gives me frontier-quality resumes at budget prices. Mistral Large for JD analysis, Luna for resume generation. That's the sweet spot for a job hunt tool that runs daily but doesn't need to be perfect on every analytical edge case.
