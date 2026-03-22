# RLM: Why the Architecture is Brilliant

> **Empirically verified on 2026-03-22** with two test runs:
> - **Run 1 (small):** MiniMax-M1, max_depth=1, max_iterations=10, 12 synthetic chunks (6,508 chars). Logs: `analysis_logs/`
> - **Run 2 (real repo):** MiniMax-M1, max_depth=2, max_iterations=20, streamlit/streamlit: 1,943 files, 153 chunks (14,455,181 chars). Logs: `analysis_logs_repo/`
>
> See `AnalysisSummary.md` for a concise summary of findings from both runs.

## The Core Insight in One Sentence

The root LM sees the user's **question** but never sees the user's **data** — *initially*. The raw data lives in a REPL variable, and the root LM can only access it by writing code. For large contexts, this forces delegation to sub-LMs. But for small contexts, the root LM can (and does) bypass delegation entirely by `print(context)` to dump the data into its own conversation history.

This turns the root model into a **strategist** and the sub-LMs into **workers** — but the separation is enforced by context window limits, not by access control.

---

## 1. The Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        USER                                 │
│                                                             │
│   rlm.completion(context="<500K chars>", root_prompt="?")   │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    ROOT LM (Strategist)                     │
│                                                             │
│   System prompt:                                            │
│     "You have a `context` variable. You have `llm_query`    │
│      and `rlm_query`. Write ```repl``` code to solve it."   │
│                                                             │
│   What it SEES:                                             │
│     - The user's QUESTION (root_prompt), every iteration    │
│     - Metadata: "context is a list, 1.2M chars, 47 chunks" │
│     - Previous iteration stdout/stderr                      │
│                                                             │
│   What it DOES NOT SEE:                                     │
│     - The actual content of `context` (the DATA)            │
│     - Sub-LM responses directly (only via print() output)   │
│                                                             │
│   What it PRODUCES:                                         │
│     ```repl                                                 │
│     chunk = context[0:5]                                    │
│     answers = llm_query_batched([                           │
│         f"Find auth logic in: {c}" for c in chunk           │
│     ])                                                      │
│     for i, a in enumerate(answers):                         │
│         print(f"Chunk {i}: {a}")                            │
│     ```                                                     │
│                                                             │
└──────────────┬──────────────────────────────────────────────┘
               │
               │ code extracted via regex: ```repl ... ```
               ▼
┌─────────────────────────────────────────────────────────────┐
│                     LocalREPL                               │
│                                                             │
│   Persistent Python namespace:                              │
│     globals: llm_query, rlm_query, FINAL_VAR, SHOW_VARS    │
│     locals:  context (the actual data), any user vars       │
│                                                             │
│   exec(code, {**globals, **locals}, {**globals, **locals})  │
│                                                             │
│   When code calls llm_query("prompt"):                      │
│     → TCP request to LMHandler → API call → response        │
│                                                             │
│   Returns: REPLResult(stdout, stderr, locals, final_answer) │
└──────────────┬──────────────────────────────────────────────┘
               │
               │ stdout/stderr appended to message_history
               ▼
┌─────────────────────────────────────────────────────────────┐
│                  NEXT ITERATION                             │
│                                                             │
│   Root LM sees (every iteration):                           │
│     1. The user's question: "How does auth work?"           │
│     2. Previous code + REPL output:                         │
│        "Chunk 0: Found auth middleware in /src/auth.py..."  │
│                                                             │
│   It knows WHAT to answer (the question) and reads          │
│   print() output to judge WHETHER it has enough info yet.   │
│   Writes more code or calls FINAL(answer).                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Why Hiding the Context from the Root LM is Brilliant

### The Naive Approach (What Everyone Else Does)

```
User: "Here's 500K chars of code. How does auth work?"
  → Stuff it all into the LM's context window
  → LM reads everything, tries to answer
  → Hits context limits, loses detail, hallucinates
```

### What RLM Does Instead

The context is loaded into a **Python variable** in the REPL, not into the LM's conversation. The root LM initially sees only metadata:

```python
# prompts.py, line 158 — this is the ONLY data the root LM gets at iteration 0
metadata_prompt = f"Your context is a {context_type} with {context_total_length} total characters,
                    and is broken up into chunks of char lengths: {context_lengths}."
```

**Verified:** In our test run, the iteration 0 prompt contained exactly this:
> "Your context is a list with 6508 total characters, and is broken up into chunks of char lengths: [544, 747, 646, 690, 503, 467, 479, 498, 426, 423, 470, 615]."

No raw chunk data appeared in the system prompt or iteration 0 user messages.

**However** — the root LM writes code that *accesses* the data, and when the context is small enough, it can dump everything into its own conversation via `print(context)`:

```python
# What the root LM actually did in our test (iteration 0):
print(type(context))   # → <class 'list'>
print(len(context))    # → 12
print(context)         # → ALL 6,508 chars dumped into REPL output → into root's context
```

**This means:** For small contexts, the root LM reads everything directly. The delegation to sub-LMs only becomes necessary when the data exceeds the 20K-char-per-code-block truncation limit or the model's context window.

### Why This Works So Well

**1. The root LM stays in its zone of competence.**

LLMs are bad at scanning 500K characters for specific facts. They're good at writing programs. By forcing the root LM to *only* write programs, you keep it doing what it's good at: decomposition, planning, control flow, branching logic.

**2. The context window is used for strategy, not storage.**

The root LM's context window holds:
- The system prompt (~3K tokens)
- Iteration history (code + truncated stdout from previous iterations)
- The user's question

It does NOT hold the actual data. This means the root LM can run 30 iterations of increasingly sophisticated analysis without ever running out of context. Each sub-LM call gets a fresh context window dedicated entirely to its chunk.

**3. Sub-LMs get focused, bounded inputs.**

Instead of one LM trying to process 1.2M characters, you get:

```
Sub-LM 1: "Find auth logic in [chunk 0, ~100K chars]"  → focused answer
Sub-LM 2: "Find auth logic in [chunk 1, ~100K chars]"  → focused answer
Sub-LM 3: "Find auth logic in [chunk 2, ~100K chars]"  → focused answer
...
Sub-LM N: "Synthesize these findings: ..."              → final answer
```

Each sub-LM has a small, focused job. They can fit their entire input in context. No information is lost.

**4. It's a natural map-reduce.**

The REPL gives you Python — loops, conditionals, variables. The root LM naturally writes map-reduce patterns:

```python
# Map phase: fan out to sub-LMs
answers = llm_query_batched([f"Analyze chunk: {c}" for c in chunks])

# Reduce phase: aggregate
final = llm_query(f"Combine these analyses: {answers}")
```

This isn't hard-coded. The root LM *chooses* the decomposition strategy based on the metadata it sees (data type, size, chunk count). Different problems get different strategies.

---

## 3. The REPL Loop: How "Knowing It's Doing Well" Actually Works

There is **no reward function**. No verifier. No judge model. The system relies on something simpler and more powerful: **observable intermediate state**.

### The Feedback Loop

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   Iteration 0                                                   │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │ Root LM: "Let me explore the context structure first"    │  │
│   │ ```repl                                                  │  │
│   │ print(type(context), len(context))                       │  │
│   │ print(context[0][:200])                                  │  │
│   │ ```                                                      │  │
│   └───────────────────────────┬──────────────────────────────┘  │
│                               │                                 │
│   REPL output → message_history:                                │
│   "REPL output: <class 'list'> 47                               │
│    # File: src/main.py\nimport flask..."                        │
│                               │                                 │
│   Iteration 1                 ▼                                 │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │ Root LM: "Ah, it's 47 file chunks. Let me search for    │  │
│   │ auth-related files first, then deep-dive."               │  │
│   │ ```repl                                                  │  │
│   │ for i, c in enumerate(context):                          │  │
│   │     if 'auth' in c.lower()[:500]:                        │  │
│   │         print(f"Chunk {i}: {c[:100]}")                   │  │
│   │ ```                                                      │  │
│   └───────────────────────────┬──────────────────────────────┘  │
│                               │                                 │
│   REPL output: "Chunk 12: # File: src/auth/middleware.py..."    │
│                "Chunk 31: # File: src/auth/tokens.py..."        │
│                               │                                 │
│   Iteration 2                 ▼                                 │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │ Root LM: "Found 2 auth files. Let me analyze them."     │  │
│   │ ```repl                                                  │  │
│   │ auth_analysis = llm_query_batched([                      │  │
│   │     f"Explain the auth flow in: {context[12]}",          │  │
│   │     f"Explain token handling in: {context[31]}"          │  │
│   │ ])                                                       │  │
│   │ for a in auth_analysis: print(a[:500])                   │  │
│   │ ```                                                      │  │
│   └───────────────────────────┬──────────────────────────────┘  │
│                               │                                 │
│   Iteration 3                 ▼                                 │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │ Root LM: "Got both analyses. Let me synthesize."         │  │
│   │ ```repl                                                  │  │
│   │ final = llm_query(f"Synthesize: {auth_analysis}")        │  │
│   │ ```                                                      │  │
│   │ FINAL_VAR(final)                                         │  │
│   └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│   ──── LOOP EXITS ────                                          │
└─────────────────────────────────────────────────────────────────┘
```

### What the Root LM's Context Actually Looks Like Over Time (Empirically Observed)

The root LM's context is **not** just metadata after iteration 0. It accumulates real content rapidly. Here are the actual measurements from our test run (12 chunks, 6,508 total chars):

```
ITERATION 0 — Root LM context: 3 messages, 11,263 chars
  [system]  ~9,700 chars — full system prompt with REPL instructions
  [user]    "Your context is a list with 6508 total characters..."  ← metadata only
  [user]    "You have not interacted with the REPL environment..."   ← the question

ITERATION 1 — Root LM context: 5 messages, 18,070 chars (+6,807)
  (everything above PLUS)
  [assistant] "I'll start by exploring..." + ```repl print(context)```
  [user]    "Code executed: ... REPL output: ['=== SUBSYSTEM: Database Layer..."
            ← ALL 6,508 chars of raw context data now in root's context
  [user]    "The history before..." + question again

ITERATION 2 — Root LM context: 7 messages, 22,023 chars (+3,953)
  (everything above PLUS)
  [assistant] code that printed specific chunks (auth, gateway, billing)
  [user]    REPL output with focused chunk data (re-printed individually)

ITERATION 3 — Root LM context: 9 messages, 27,309 chars (+5,286)
  (everything above PLUS)
  [assistant] composed final answer as variable, printed it
  [user]    REPL output with the compiled answer text
  — Root LM decides "I have enough" on NEXT iteration → emits FINAL_VAR(answer)
```

**Key finding (Run 1, small):** By iteration 1, the root LM had ALL the raw data in its context via `print(context)`. No sub-LMs were used at all. Total: 4 iterations, 0 sub-LM calls, 27K chars in root context at termination.

**Key finding (Run 2, streamlit/streamlit — 14.5M chars, 153 chunks):** The architecture works completely differently at scale:
```
Iteration 0:  3 msgs, 11,625 chars — metadata only
Iteration 1:  5 msgs, 31,957 chars (+20K) — print(context[:3]) truncated at 20K
Iteration 5:  13 msgs, 43,934 chars — keyword searching for 'cache' across chunks
Iteration 10: 23 msgs, 65,872 chars — reading specific cache files
Iteration 15: 33 msgs, 100,938 chars — sub-LM responses landing
Iteration 17: 37 msgs, 123,767 chars — 3 llm_query calls completed
Iteration 19: 41 msgs, 131,441 chars — trying to terminate (hit max iterations)
```
At scale: 20 iterations, 3 sub-LM calls (15K, 18K, 1.3K char prompts), 1 truncation event (741K→20K, lost 97.3%), 131K chars in root context. Sub-LM delegation was forced by the 20K truncation limit — the root LM physically could not read the chunks directly.

The key mechanism: `format_iteration()` (`parsing.py:73-105`) appends **full stdout** from code execution (truncated at 20,000 chars per code block) to `message_history`. So `print(context)` or `print(answer)` after an `llm_query()` call puts real data/responses into the root LM's context for all future iterations.

**This means the root LM CAN read data directly** — the separation is enforced by the 20K truncation limit and model context window, not by any access control. For small contexts (<20K chars), the root LM simply dumps and reads everything. For large contexts, truncation forces delegation.

### How the Root LM Decides When It's Done (The Honest Answer — Empirically Verified)

The root LM sees the user's question **every single iteration** — confirmed. In our test, every iteration's last user message contained the full root_prompt text.

**The system prompt never tells it how to evaluate sufficiency.** The only instruction about termination is:

```
"When you are done with the iterative process, you MUST provide a final
answer inside a FINAL function when you have completed your task."
```

**Verified:** We searched the full system prompt (~9,700 chars) for evaluation criteria. The word "sufficient" appears twice but only in the context of "look through it sufficiently" and "is sufficient to just fit it in a few sub-LLM calls" — neither is a termination criterion. There is no "evaluate whether you're done", "check if you have enough", "verify your answer", "assess completeness", or "stop when" instruction. **Contains evaluation criteria? NO.**

**Observed termination behavior:** The model terminated at iteration 3 via `FINAL_VAR(answer)` (detected as `FINAL_VAR_in_REPL`). At that moment, the root LM's context contained 26,615 chars across 8 messages. The model had:
1. Dumped all context data (iteration 0)
2. Re-read specific chunks — auth, gateway, billing (iteration 1)
3. Composed a structured answer as a Python variable (iteration 2)
4. Called `FINAL_VAR(answer)` (iteration 3)

This is both a strength and a weakness:

- **Strength**: The model used its general intelligence to judge completeness. It identified 4 sub-questions, found the relevant chunks (1, 2, 3), and composed a comprehensive answer covering all 4 points. No rigid criteria needed.
- **Weakness**: The model never queried chunks 4-11 (notifications, search, deployment, monitoring, data pipeline, file storage, admin, compliance). The compliance chunk (11) contains auth-relevant info (JWT tenant_id claim) that was missed. It stopped based on "feels complete" not "verified complete."
- **Weakness**: The accumulated print() output can be truncated (20K char limit per code block). In our test, no truncation occurred (total output was under 20K), but with larger contexts this would bite.

---

## 4. Why Delegating the "Deciding" to Sub-LMs is the Key Move

### The Root LM is a Programmer, Not a Reader

Here's the critical asymmetry — **with an important caveat revealed by our test:**

| | Root LM | Sub-LMs |
|---|---|---|
| **Sees the question** | Yes (root_prompt, every iteration) | Only what root LM passes in the prompt string |
| **Sees the data** | **Initially no** (only metadata). But can access it via `print()` — and DOES for small contexts. | Yes (full chunks, via interpolated f-strings) |
| **Writes code** | Yes (the whole point) | No (just answers) |
| **Makes strategy decisions** | Yes (how to decompose) | No (just executes) |
| **Decides what matters** | **Can do this too** when data is small enough to print | Yes (extracts, summarizes, judges) for large data |
| **Iterates** | Yes (up to 30 rounds) | No (one-shot via `llm_query`) |

**Empirical correction:** In our test (6.5K char context), the root LM made 0 sub-LM calls. It `print(context)` to read all data, identified relevant chunks itself, composed the answer in Python code, and called FINAL_VAR. The sub-LM delegation pattern only activates when the data is too large to fit in print() output (>20K chars per code block).

The sub-LMs are the ones actually *reading* and *understanding* the data **for large contexts**. For small-to-medium contexts, the root LM can and does handle everything alone. This separation means:

**The root model scales to arbitrary input sizes** because *when the data is too large*, it delegates to sub-LMs rather than trying to hold the data. But the delegation is emergent behavior driven by context window pressure, not enforced by architecture.

**The sub-LMs produce high-quality answers** because each one gets a focused, bounded input — the exact chunk it needs to analyze, with a clear question.

### Recursive Depth Makes This Even More Powerful (In Theory — Not Observed in Practice)

When `max_depth > 1`, sub-LMs *can* get their own REPL loops via `rlm_query()`:

```
max_depth=1:  Root (REPL) → sub-LM (one-shot via llm_query or rlm_query)
max_depth=2:  Root (REPL) → child RLM (REPL) → sub-LM (one-shot)
max_depth=3:  Root (REPL) → child (REPL) → grandchild (REPL) → sub-LM (one-shot)
```

The key distinction: `llm_query()` is **always** one-shot regardless of depth. Only `rlm_query()` spawns a child RLM with its own REPL — and only if `depth < max_depth` (`rlm.py:300-301`).

```
Root LM (depth=0, strategist)
  │
  ├─ rlm_query("Analyze auth flow in chunk 12")
  │    └─ Child RLM (depth=1, gets its own REPL)
  │         ├─ Iteration 0: explores chunk 12
  │         ├─ Iteration 1: llm_query() to extract details
  │         ├─ Iteration 2: FINAL(detailed analysis)
  │         └─ returns result to parent
  │
  ├─ rlm_query("Analyze token handling in chunk 31")
  │    └─ Child RLM (depth=1, gets its own REPL)
  │         └─ ...same iterative process...
  │
  └─ Root combines results → FINAL(answer)
```

Each child gets:
- Its own REPL namespace
- Its own iteration budget
- A slice of the parent's time/money budget (`rlm.py:708-736`)
- No knowledge of the parent's broader strategy

This is fractal decomposition. Hard problems get recursively broken down until each leaf sub-problem is simple enough for a one-shot LM call.

> **Empirical status: NOT TESTED.** In our Run 2 (max_depth=2, streamlit/streamlit), the root LM made 3 `llm_query()` calls and **0 `rlm_query()` calls** — the recursive depth capability was never exercised. The model chose fast one-shot calls over slower recursive ones, even when depth budget was available. This suggests that the recursive depth feature may require either (a) larger/harder tasks where one-shot answers are insufficient, (b) explicit prompting to encourage `rlm_query()` usage, or (c) a different model that naturally reaches for deeper tools. The `rlm_query` vs `llm_query` choice is entirely up to the model — the system prompt describes both but doesn't push one over the other.

---

## 5. The Prompt Architecture: What Each Layer Sees

### Layer 1: System Prompt (what shapes the root LM's behavior)

From `prompts.py`:

```
"You are tasked with answering a query with associated context.
 You can access, transform, and analyze this context interactively
 in a REPL environment that can recursively query sub-LLMs..."
```

Key instructions:
- "You must break problems into more digestible components"
- "Use the REPL to write a **programmatic strategy** that uses these LLM calls to solve the problem, **as if you were building an agent**"
- "You will only be able to see truncated outputs from the REPL environment, so you should use the query LLM function on variables you want to analyze"

That last line is crucial. It tells the root LM: *you can't read the data yourself, you must delegate reading to sub-LMs*.

### Layer 2: Metadata Prompt (what the root LM actually knows about the data)

```python
# prompts.py:158
"Your context is a list with 1200000 total characters,
 and is broken up into chunks of char lengths: [25000, 31000, ...]"
```

Just the shape. Not the content. This is enough for the root LM to write a chunking strategy.

### Layer 3: User Prompt (repeated EVERY iteration — this is how the root LM knows the question)

```python
# prompts.py:167 — this is appended to every single iteration's prompt
USER_PROMPT_WITH_ROOT = """Think step-by-step on what to do using the REPL environment
(which contains the context) to answer the original prompt: \"{root_prompt}\".
Continue using the REPL environment... Your next action:"""
```

```python
# rlm.py:341-343 — root_prompt is baked in every iteration
current_prompt = message_history + [
    build_user_prompt(root_prompt, i, context_count, history_count)
]
```

This is the crucial piece: **the root LM always knows what question it's answering**. It sees "answer the original prompt: 'How does auth work?'" at the bottom of every single iteration. So when it reads print() output from sub-LMs and sees enough auth-related information, it can judge: "yes, I can now answer 'How does auth work?'" and emit FINAL().

### Layer 4: Iteration Feedback (what the root LM learns from running code)

```
Code executed:
```python
answers = llm_query_batched([...])
```

REPL output:
Chunk 0: Found JWT validation in middleware...
Chunk 1: No auth-related code found...
REPL variables: ['answers', 'chunk', 'auth_files']
```

This is the only "reward signal." The root LM compares this output against the question it sees every iteration (via `root_prompt`) and decides: do I have enough to answer, or do I need more iterations?

---

## 6. Why This Beats Traditional Approaches

### vs. RAG (Retrieval-Augmented Generation)

RAG retrieves fixed-size chunks via embedding similarity. Problems:
- Embedding similarity misses semantic connections
- Fixed chunk sizes break logical units
- One retrieval pass — no iterative refinement

RLM lets the model **write its own retrieval strategy**. It can search by keyword, filter by file type, chunk by logical boundaries, re-query chunks that seem promising. The retrieval strategy is a *program*, not a fixed pipeline.

### vs. Long-Context Models

Even with 1M+ token windows, quality degrades with length. The "needle in a haystack" problem doesn't go away — it just moves. Models lose track of information in the middle of long contexts.

RLM sidesteps this entirely. No single LM ever sees the full context. Each sub-LM sees a focused slice. The root LM only sees structured summaries from those sub-LMs.

### vs. Agent Frameworks (LangChain, CrewAI, etc.)

Agent frameworks give LMs tools (search, read_file, etc.) and let them decide what to call. Problems:
- Tool calls are atomic — no persistent state between calls
- The LM still has to hold everything in its context window
- Tool selection is a classification problem the LM may get wrong

RLM gives the LM a **full programming language**. Variables persist. Control flow (if/else, loops) is native. The LM doesn't "select tools" — it writes programs that compose tools. This is strictly more expressive.

---

## 7. The Termination Mechanism

The loop exits via one of these paths:

```
                    ┌─────────────────────┐
                    │   REPL Iteration     │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
              ┌─────┤  FINAL() detected?  ├─────┐
              │ yes └─────────────────────┘ no  │
              │                                 │
              ▼                                 ▼
     ┌────────────────┐              ┌──────────────────┐
     │  Return answer │         ┌────┤ Limits exceeded? ├────┐
     └────────────────┘         │yes └──────────────────┘ no │
                                │                            │
                                ▼                            ▼
                    ┌───────────────────────┐   ┌────────────────────┐
                    │ Return best partial   │   │ i < max_iterations?│
                    │ or _default_answer()  │   └────────┬───────────┘
                    └───────────────────────┘        yes  │   no
                                                         │    │
                                                         ▼    ▼
                                                  next iter  _default_answer()
```

Detection happens in two places:
1. **Inside REPL execution** — `FINAL_VAR(x)` sets `_last_final_answer` on the `REPLResult` (`local_repl.py:552`)
2. **In the response text** — regex matches `FINAL(...)` outside code blocks (`parsing.py:65`)

The REPL-based detection is checked first (`rlm.py:357-360`), then the text-based fallback (`rlm.py:361-364`).

---

## 8. Summary: The Three Brilliant Decisions (and Two Honest Limitations)

> Updated with empirical data from a live test run (MiniMax-M1, 12 chunks, 6,508 chars, 4 iterations, 0 sub-LM calls).

1. **Question visible, data hidden (at first).** The root LM sees the user's question every iteration (via `root_prompt`) — **confirmed: present in all 4 iterations**. The raw data lives in a REPL variable, not the context window — **confirmed: iteration 0 had only metadata, no raw chunk data**. However, the root LM can `print(context)` to pull raw data into its own context — **confirmed: by iteration 1, all 6,508 chars of raw data were in the root LM's history**. The "data hidden" property is enforced by the 20K truncation limit and context window pressure, not by access control.

2. **Code as the interface.** Instead of tool-calling or function-calling APIs, the LM writes Python. This gives it loops, conditionals, variables, string manipulation — the full power of a programming language. **Observed:** The root LM used this to select specific chunks (`context[1]`, `context[2]`, `context[3]`), compose a structured answer as a multi-line string variable, and call `FINAL_VAR(answer)`. No sub-LMs needed — Python itself was sufficient for this task size.

3. **Sub-LMs as the actual readers (for large contexts).** **Confirmed in Run 2:** With streamlit/streamlit (14.5M chars), the root LM made 3 `llm_query` calls with 15K-18K char prompts containing actual Python source code. Sub-LMs returned 5K-18K char analyses. The delegation pattern activates when truncation (20K limit) prevents the root LM from reading chunks directly. In Run 1 (6.5K chars), the root LM handled everything alone — 0 sub-LM calls. The delegation is emergent behavior driven by context window pressure.

**Limitation 1: Termination is an uninstructed best guess.** **Confirmed:** The system prompt contains no evaluation criteria (we searched for "evaluate whether", "check if you have enough", "verify your answer", "assess completeness", "stop when", "sufficient information" — none found). The root LM stopped at iteration 3 with a good answer covering all 4 sub-questions, but missed auth-relevant info in chunks it never queried (e.g., chunk 11's JWT tenant_id claim for cross-tenant access prevention). Detection method: `FINAL_VAR_in_REPL`.

**Limitation 2: Small contexts bypass the architecture's key strength.** When the data fits in a single `print()` output (<20K chars), the root LM reads everything directly and never delegates (Run 1: 0 sub-LM calls for 6.5K chars). The sub-LM decomposition only engages for genuinely large inputs (Run 2: 3 sub-LM calls for 14.5M chars).

**Limitation 3: Termination mechanism is fragile.** Run 2 exposed a bug: the model wrote `FINAL(final_explanation)` inside a `repl` block, but `FINAL` wasn't a REPL function. The code raised `NameError`, and the text-regex fallback returned the literal string `"final_explanation"` (17 chars) instead of the 18K-char answer. The model had a complete, high-quality answer ready at iteration 17 but couldn't extract it for 2 more iterations and ultimately failed. **(Fix applied: `FINAL()` is now registered as a REPL function.)**

**Limitation 4: Truncation is brutal.** A single `print(context[:3])` on 3 chunks (725K chars) was truncated to 20K — losing 97.3% of the content. This is by design (it forces delegation), but means any `print()` of large data is nearly useless for direct reading. The root LM must learn to use targeted reads (`context[N][:K]`) or delegate to sub-LMs.

The result: a system that can process arbitrarily large inputs, iteratively refine its approach based on intermediate results, and naturally parallelize work — all without any training, fine-tuning, or reward modeling. The delegation to sub-LMs is an emergent property that scales up with data size, not a fixed pipeline.

---

## 9. What RLM Actually Does (The Honest Version)

Strip away the REPL loop, the recursion depth, the "strategist" framing — what is actually happening at the end of the day?

### The Pipeline

```
1. os.walk() the repo → read every source file into a flat list
2. Split that list into ~100K char chunks (sequential, no ranking)
3. Give the LLM a REPL with the chunks as a variable
4. The LLM writes code that stuffs chunks into sub-LM calls with the user's question
5. Sub-LM answers come back → LLM synthesizes → FINAL()
```

**There is no retrieval.** No BM25, no TF-IDF, no embedding similarity, no keyword ranking. The `index.py` walks the directory tree and reads files in `os.walk` order. The `to_context_chunks()` method packs files sequentially until a chunk hits 100K chars, then starts a new chunk. The ordering is arbitrary — it's directory-walk order, not relevance order.

**There is no filtering.** Every source file that matches the extension list and is under 256KB gets indexed. Test files can be excluded via a flag, but that's it. No static analysis, no dependency graph, no "what files are relevant to auth?" preprocessing.

### What the LLM "Strategy" Actually Looks Like

The system prompt tells the root LM to "write a programmatic strategy" and "break problems into digestible components." In practice, the emergent strategy is almost always one of two patterns:

**Pattern A — Small context (fits in print output, <20K chars):**
```python
print(context)  # dump everything into my own context
# ... read it myself, compose answer, done
```
No sub-LM calls. No decomposition. Just "print and read." RLM is an LLM with a Python scratchpad.

**Pattern B — Large context (>20K chars, truncation forces delegation):**
```python
# Map: ask the same question over every chunk
prompts = [f"Answer '{question}' from this chunk:\n{chunk}" for chunk in context]
answers = llm_query_batched(prompts)

# Reduce: synthesize
final = llm_query(f"Combine these answers:\n{answers}")
```
This is map-reduce. Fan out the user's question to every chunk, collect answers, synthesize. The "programmatic strategy" the LLM writes is the same pattern every time — because it's the obvious thing to do when you have chunks and a question.

### The Only Potentially Novel Behavior: Iterative Refinement

The one thing the REPL loop enables that a simple map-reduce pipeline doesn't:

1. **Keyword filtering before dispatch.** The LLM *can* write code like:
   ```python
   for i, c in enumerate(context):
       if 'auth' in c.lower():
           print(f"Chunk {i} is relevant")
   ```
   Then only send relevant chunks to sub-LMs. This is basic keyword search — `str.__contains__` — not BM25 or anything sophisticated. And it's not guaranteed to happen; it depends on what the LLM decides to write.

2. **Going back for more.** If the first round of sub-LM answers isn't sufficient, the root LM can iterate — query different chunks, ask follow-up questions, dig deeper into a specific chunk. This is the "recursive" part that a one-shot pipeline can't do.

But let's be honest about what "going back" means: the root LM reads the sub-LM answers, compares them against the question (which it sees every iteration), and decides "I need more." Then it writes more code to query more chunks. It's a retry loop with the LLM as the loop condition. Useful, but not magic.

### What RLM Is NOT

- **Not a retrieval system.** No relevance ranking, no embeddings, no search index. Every chunk gets the same treatment unless the LLM happens to write filtering code.
- **Not a novel decomposition strategy.** The LLM writes the same map-reduce pattern that you'd hardcode in 20 lines of Python. The REPL is the delivery mechanism, not the innovation.
- **Not "recursive" in most practical cases.** At the default `max_depth=1`, sub-LM calls are one-shot — no REPL, no iteration. The "recursive" part (sub-LMs getting their own REPLs) only activates at `max_depth >= 2`, which is not the default.

### What RLM IS (Charitably)

- **A flexible harness** for letting an LLM decide how to process large context. The REPL loop means the LLM can adapt its strategy based on what it finds — keyword filter, multi-pass, selective deep-dive. Whether it actually does this depends on the model and the question.
- **A parallelization wrapper.** `llm_query_batched()` fans out to multiple sub-LMs concurrently. This is genuinely useful — processing 10 chunks in parallel is faster than sequential.
- **A context window multiplier.** Instead of one LLM trying to process 1M chars, you get N sub-LMs each processing ~100K chars. The total "reading capacity" scales with the number of chunks.

### The Bottom Line

RLM's core operation for repo Q&A is: **index all files → chunk sequentially → let the LLM stuff chunks into sub-LM calls with the user's question → synthesize answers.** The REPL loop adds the ability to keyword-filter before dispatch and iterate if the first pass isn't enough. That's the whole thing. The architecture is elegant, but the emergent behavior is straightforward map-reduce with an optional retry loop.
