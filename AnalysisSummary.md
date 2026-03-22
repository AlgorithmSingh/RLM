# RLM Analysis — Empirical Verification Summary

**Date:** 2026-03-22
**Model:** MiniMax-M1 via OpenAI-compatible API
**Config:** max_depth=1, max_iterations=10, environment=local
**Context:** 12 synthetic chunks describing a fictional distributed system (6,508 chars total)
**Question:** Multi-part auth/authorization question requiring synthesis across 3+ chunks
**Logs:** `analysis_logs/deep_log.jsonl`, `analysis_logs/final_moment_history.json`

---

## Claim Verification

| # | Claim from Analysis.md | Verified? | Evidence |
|---|---|---|---|
| 1 | Root LM sees the question every iteration | **YES** | `root_prompt` text present in all 4 iterations' last user message |
| 2 | Root LM does NOT see raw context data (initially) | **YES** | Iteration 0: system prompt and user messages contain zero raw chunk text. Only metadata: "list with 6508 total characters, chunks of char lengths: [544, 747, ...]" |
| 3 | Root LM's context accumulates via print() | **YES** | Iter 0: 11,263 chars (3 msgs) → Iter 1: 18,070 (+6,807) → Iter 2: 22,023 (+3,953) → Iter 3: 27,309 (+5,286). By iteration 1, ALL raw data was in context via `print(context)` |
| 4 | Sub-LMs get focused prompts with chunk data | **NOT TESTED** | 0 sub-LM calls were made. The root LM read all data directly. This claim is architecturally correct (the code interpolates chunks into f-strings), but was not exercised in this run. |
| 5 | Truncation happens at 20K chars per code block | **NOT TRIGGERED** | No truncation occurred. Total context was 6,508 chars — well under the 20K limit. |
| 6 | No sufficiency criteria in termination | **YES** | System prompt searched for: "evaluate whether", "check if you have enough", "verify your answer", "assess completeness", "stop when", "sufficient information" — none found. The word "sufficient" appears only in "look through it sufficiently" and "is sufficient to just fit it in a few sub-LLM calls." |
| 7 | System prompt has no "evaluate whether you're done" | **YES** | The only termination instruction: "When you are done with the iterative process, you MUST provide a final answer inside a FINAL function when you have completed your task." No criteria for what "done" means. |

---

## The Numbers

| Metric | Value |
|---|---|
| Total iterations | 4 |
| llm_query calls | 0 |
| llm_query_batched calls | 0 |
| rlm_query calls | 0 |
| Truncation events | 0 |
| FINAL() events | 1 |
| Detection method | FINAL_VAR_in_REPL |
| Final iteration | 3 (0-indexed) |
| Root context at FINAL() | 26,615 chars, 8 messages |
| Final root context (after formatting) | 27,309 chars, 9 messages |
| Final answer length | 1,610 chars |
| Total execution time | 41.32s |
| Total input tokens | 18,145 |
| Total output tokens | 1,336 |

---

## What the Root LM Actually Did (Trace)

**Iteration 0** — Exploration
```python
print(type(context))    # → <class 'list'>
print(len(context))     # → 12
print(context)          # → dumps ALL 6,508 chars into REPL output
```
Root LM now has all raw data in its context. No sub-LMs needed.

**Iteration 1** — Focused reading
Identified relevant chunks by content (auth=chunk 1, gateway=chunk 2, billing=chunk 3). Printed them individually. Still no sub-LM calls — the root LM is reading and analyzing the data itself.

**Iteration 2** — Answer composition
Composed a structured multi-part answer as a Python variable `answer`, covering all 4 sub-questions. Printed it for verification. The answer synthesized info from chunks 1, 2, 3, and 8 (data pipeline's service-account API keys).

**Iteration 3** — Termination
Called `FINAL_VAR(answer)` to return the composed answer. Detected via REPL execution (not text regex).

---

## Key Corrections to the Original Analysis

### 1. "The root LM never sees the raw data" — Partially wrong

The root LM **initially** doesn't see raw data (iteration 0 only has metadata). But it can `print(context)` to dump all data into its own conversation history. For our 6.5K char context, it did exactly this on iteration 0.

**The corrected claim:** The root LM doesn't see raw data *in its initial prompt*. But nothing prevents it from reading the data via print(). The delegation to sub-LMs is forced by the 20K-per-code-block truncation limit and the model's context window, not by access control.

### 2. "Sub-LMs are the actual readers" — Only for large contexts

In our test, the root LM made **zero** sub-LM calls. It read, analyzed, and synthesized all data itself using Python string operations and direct chunk access. The sub-LM delegation pattern is an emergent behavior that only activates when the data is too large for direct reading.

### 3. Termination quality — Good but incomplete

The root LM produced a correct, well-structured answer covering all 4 sub-questions. However, it only queried chunks 0-3 and 10 (via direct access), never looking at chunks 4-11. The compliance chunk (11) contains auth-relevant info about JWT tenant_id claims preventing cross-tenant access — this was missed.

**Is the FINAL() decision informed or a best guess?** It's an informed best guess. The root LM had read substantial relevant data (auth service, API gateway, billing) and composed a coherent answer. But it didn't verify completeness — it never checked whether other chunks contained auth-relevant info.

---

## The System Prompt Around Termination (Exact Text)

The only termination-related passages in the system prompt:

> "You will be queried iteratively until you provide a final answer."

> "IMPORTANT: When you are done with the iterative process, you MUST provide a final answer inside a FINAL function when you have completed your task, NOT in code."

> "WARNING - COMMON MISTAKE: FINAL_VAR retrieves an EXISTING variable."

There is **no** instruction like:
- "Verify your answer covers all aspects of the question"
- "Check if there are chunks you haven't examined"
- "Evaluate whether you have sufficient information"
- "Stop when [criteria]"

The root LM decides "done" based on its own judgment, informed by the question it sees every iteration and the data it has accumulated.

---

## Answering the Driving Questions

**1. Does the root LM really never see the raw data?**
No. It sees raw data by iteration 1 (via `print(context)`). The "never sees the data" claim only holds for the initial prompt. The separation is enforced by truncation limits on large contexts.

**2. How much sub-LM content ends up in the root LM's context?**
Zero in our test — no sub-LMs were called. The context grew from 11,263 → 27,309 chars entirely from direct print() output of raw data and the composed answer.

**3. What does the root LM's context look like at FINAL()?**
26,615 chars across 8 messages. Contains: system prompt (~9.7K), metadata prompt, all raw context data (via print), re-printed focused chunks, the composed answer. It's making an informed decision with rich data in context.

**4. Is 20K chars per code block enough?**
Not tested — our context was only 6.5K. No truncation occurred. This question requires a test with >20K char chunks.

**5. Could the root LM have gotten a better answer with one more iteration?**
Possibly. It never examined chunks 4-11. Chunk 11 (compliance) has JWT tenant_id info relevant to authorization. Chunk 5 (search service) has tenant-based search filtering. These would have strengthened the answer. The root LM stopped after 4 iterations out of a max of 10 — it had budget to continue but chose not to.

**6. What prompts are actually sent to sub-LMs?**
Not observed — no sub-LM calls were made. The architecture passes chunks via interpolated f-strings (e.g., `f"Analyze: {context[12]}"`), but this path was never taken.
