# RLM Analysis — Empirical Verification Summary

## Two Test Runs

| | Run 1: Synthetic | Run 2: Real Repo |
|---|---|---|
| **Date** | 2026-03-22 | 2026-03-22 |
| **Model** | MiniMax-M1 | MiniMax-M1 |
| **Config** | max_depth=1, max_iterations=10 | max_depth=2, max_iterations=20 |
| **Context** | 12 synthetic chunks (6,508 chars) | streamlit/streamlit: 1,943 files, 153 chunks (14,455,181 chars) |
| **Question** | Multi-part auth/authorization | "Explain the caching system" |
| **Logs** | `analysis_logs/` | `analysis_logs_repo/` |

---

## Claim Verification (Both Runs)

| # | Claim | Run 1 (small) | Run 2 (real repo) |
|---|---|---|---|
| 1 | Root LM sees question every iteration | **YES** — all 4 iters | **YES** — all 20 iters |
| 2 | Root LM doesn't see raw data initially | **YES** — only metadata at iter 0 | **YES** — iter 0 had only metadata: "list with 14455181 total characters, chunks of char lengths: [541797, 84938, ...]" |
| 3 | Context accumulates via print() | **YES** — 11K→27K chars | **YES** — 11K→131K chars over 20 iters |
| 4 | Sub-LMs get focused prompts with chunk data | **NOT TESTED** (0 calls) | **YES** — 3 llm_query calls. Prompts contained actual code: `cache_utils.py` (15K chars), `hashing.py` (18K chars), synthesis prompt (1.3K chars) |
| 5 | Truncation at 20K chars per code block | **NOT TRIGGERED** | **YES** — 1 event: 741,926 → 20,000 chars (lost 721,926 chars = 97.3%) |
| 6 | No sufficiency criteria in termination | **YES** | **YES** — same system prompt |
| 7 | No "evaluate whether done" instruction | **YES** | **YES** — confirmed same 6 phrases absent |

---

## The Numbers

| Metric | Run 1 (Synthetic) | Run 2 (streamlit/streamlit) |
|---|---|---|
| Total iterations | 4 | **20 (hit max!)** |
| llm_query calls | 0 | **3** |
| llm_query_batched calls | 0 | 0 |
| rlm_query calls | 0 | 0 |
| Truncation events | 0 | **1 (741K → 20K, lost 722K chars)** |
| FINAL() events | 1 | 1 |
| Detection method | FINAL_VAR_in_REPL | **FINAL_in_text** |
| Final iteration | 3 | **19** |
| Root context at FINAL() | 26,615 chars, 8 msgs | **131,046 chars, 40 msgs** |
| Final answer length | 1,610 chars | **17 chars (BROKEN)** |
| Total execution time | 41.3s | **347.2s** |
| Total input tokens | 18,145 | **371,758** |
| Total output tokens | 1,336 | **15,124** |

---

## Run 1: Synthetic Context (Small) — Trace

**Iteration 0** — `print(context)` dumps ALL 6,508 chars. No sub-LMs needed.
**Iteration 1** — Selects relevant chunks (auth, gateway, billing), prints them individually.
**Iteration 2** — Composes structured answer as Python variable.
**Iteration 3** — `FINAL_VAR(answer)` → clean exit. Good answer (1,610 chars).

---

## Run 2: streamlit/streamlit (Large) — Trace

**Iteration 0** — `print(context[:3])` → first 3 chunks dumped. Hit 20K truncation on first chunk (541K chars). Root LM got the directory tree + truncated code.

**Iterations 1-8** — Keyword search across chunks. Wrote code like:
```python
for i, chunk in enumerate(context):
    if 'cache' in chunk.lower()[:500]:
        print(f"Chunk {i}: {chunk[:200]}")
```
Found cache-related chunks. Printed previews. Context grew steadily: 31K → 53K chars.

**Iterations 9-14** — Deeper exploration. Extracted specific files (`cache_utils.py`, `hashing.py`, decorator implementations). Read code directly via `context[N]` and printed sections. Context: 59K → 93K chars.

**Iterations 15-17** — Sub-LM calls finally triggered:
- `llm_query(f"Analyze this Streamlit cache_utils.py code...")` — 15K char prompt → 5K response
- `llm_query(f"Explain this Streamlit hashing.py code...")` — 18K char prompt → 12K response
- `llm_query("Create a comprehensive explanation...")` — 1.3K synthesis prompt → 18K response

Context jumped: 100K → 123K chars after sub-LM responses landed.

**Iterations 18-19** — Tried to terminate. Wrote `final_answer = final_explanation` and then `FINAL(final_explanation)` inside a code block. **FINAL is not a REPL function** (only FINAL_VAR is), so it threw `NameError`. The text-regex fallback caught `FINAL(final_explanation)` in the response text and returned the literal string `"final_explanation"` — **the variable name, not its 18K-char value**.

**Result:** Broken termination. The model had a good 18K-char answer in the `final_explanation` variable but failed to extract it because it confused `FINAL()` (text-level) with `FINAL_VAR()` (REPL-level).

---

## Key Findings Across Both Runs

### 1. "The root LM never sees the raw data" — Nuanced

- **Small context (Run 1):** Root LM `print(context)` and read everything directly. ALL raw data in its context by iteration 1. Zero sub-LM calls.
- **Large context (Run 2):** Root LM cannot dump 14.5M chars — truncation at 20K kicks in immediately. It reads *previews* and *selected sections*, but most data is accessed only via sub-LM calls with chunks interpolated into prompts.
- **Corrected claim:** The root LM doesn't see raw data in its initial prompt. For small contexts it reads everything directly. For large contexts, the 20K truncation limit forces delegation — but the root LM still reads substantial amounts of code directly via targeted `print(context[N][:K])` calls.

### 2. Sub-LMs DO get focused prompts with real code (Run 2 confirms)

Three sub-LM calls observed, each with actual source code in the prompt:
- `cache_utils.py` analysis: 15,232-char prompt, 5,135-char response
- `hashing.py` analysis: 18,197-char prompt, 12,174-char response
- Synthesis: 1,321-char prompt summarizing findings, 18,319-char response

Sub-LM prompts contained real Python code (`def`, `class`, `import`) — confirming the architecture works as designed for large contexts.

### 3. Truncation is massive and lossy (Run 2 reveals)

One truncation event: **741,926 → 20,000 chars** (lost 97.3%). The first `print(context[:3])` tried to dump 3 chunks (541K + 84K + 99K chars) into REPL output, which was truncated to 20K. The root LM lost almost all of the first 3 chunks' content. This forced it to use targeted reads (`context[N][:K]`) for subsequent exploration.

### 4. Termination is fragile (Run 2 reveals)

Run 2 exposed a termination bug: the model wrote `FINAL(final_explanation)` inside a `repl` code block, but `FINAL` was not a REPL function — only `FINAL_VAR` was. The code raised `NameError`, and the text-regex fallback captured the literal string `"final_explanation"` (17 chars) instead of the 18K-char answer stored in that variable.

**Fix already applied:** `FINAL()` is now registered as a REPL function (`self.globals["FINAL"] = self._final`) that accepts a direct value.

### 5. The root LM burned 20 iterations without finishing cleanly

Run 2 hit the max iteration limit (20). The model spent:
- Iterations 0-8: exploring and keyword-searching chunks
- Iterations 9-14: reading specific cache-related files
- Iterations 15-17: making 3 sub-LM calls and getting a comprehensive answer back
- Iterations 18-19: trying (and failing) to terminate

The 18K-char answer was ready by iteration 17, but it took 2 more iterations to attempt FINAL — and even then, it failed. The model had 3 iterations of budget left but couldn't figure out the right termination syntax.

### 6. Recursive depth (rlm_query) was never exercised

Run 2 used `max_depth=2`, giving the root LM the ability to spawn child RLMs with their own REPLs via `rlm_query()`. **It never did.** All 3 sub-LM calls used `llm_query()` (one-shot, no REPL).

This means:
- The `rlm_query` / recursive depth feature is **untested** in our runs
- The model prefers fast one-shot calls even when deeper reasoning is available
- `max_depth=2` vs `max_depth=1` made no practical difference in this run
- Testing `rlm_query` would require either a harder task, explicit prompting, or a model more inclined to use recursive tools

The distinction matters: `llm_query()` is always one-shot regardless of `max_depth`. Only `rlm_query()` spawns a child with its own REPL. The system prompt describes both equally — it doesn't push the model toward one or the other.

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

## Answering the Driving Questions (Updated with Both Runs)

**1. Does the root LM really never see the raw data?**
It depends on context size. Small (<20K): root LM reads everything directly via `print(context)`. Large (14.5M): root LM sees truncated previews and targeted excerpts, but most data is accessed only through sub-LM calls. The "never sees the data" claim is aspirational — the architecture *encourages* delegation via truncation limits, but doesn't *enforce* it.

**2. How much sub-LM content ends up in the root LM's context?**
Run 1: Zero (no sub-LMs used). Run 2: ~35K chars of sub-LM response text landed in the root context (5K + 12K + 18K from 3 calls). The root context grew from 11K to 131K over 20 iterations — the sub-LM responses were about 27% of the total growth.

**3. What does the root LM's context look like at FINAL()?**
Run 1: 26K chars, 8 messages — clean, well-organized. Run 2: 131K chars, 40 messages — massive, containing truncated chunk previews, keyword search results, extracted code sections, and 3 sub-LM analysis responses. The root LM was making its decision with rich context but also a lot of noise.

**4. Is 20K chars per code block enough?**
**No.** Run 2 showed a single truncation event that lost 721,926 chars (97.3%). The root LM tried to print 3 chunks totaling ~725K chars and got only 20K. This is by design — it forces delegation — but means the root LM's direct reads of large chunks are severely limited. The truncation is what makes the architecture *work* for large contexts: without it, the root LM would try to read everything itself.

**5. Could the root LM have gotten a better answer with more iterations?**
Run 1: Yes — missed chunks 4-11. Run 2: The answer was actually ready by iteration 17 (18K chars in `final_explanation`), but the model wasted iterations 18-19 trying to terminate and ultimately returned a broken 17-char answer. More iterations wouldn't help — the termination mechanism was the bottleneck, not analysis depth.

**6. What prompts are actually sent to sub-LMs?**
Run 2 observed 3 calls:
- `"Analyze this Streamlit cache_utils.py code and explain: 1. The main classes..."` + 15K chars of actual Python source
- `"Explain this Streamlit hashing.py code focusing on: 1. How the hashing mechanism..."` + 18K chars of source
- `"Create a comprehensive explanation of the Streamlit caching system based on these analysis notes: ..."` — 1.3K synthesis prompt

The prompts are well-structured: a clear question followed by the actual code. The sub-LMs receive focused, bounded inputs as the architecture intended.
