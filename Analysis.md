# RLM: Why the Architecture is Brilliant

## The Core Insight in One Sentence

The root LM never sees the user's data. It only writes *programs* that delegate actual understanding to sub-LMs. This turns the root model into a **strategist** and the sub-LMs into **workers** — and that separation is the whole trick.

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
│     - Metadata: "context is a list, 1.2M chars, 47 chunks" │
│     - root_prompt: "How does auth work?"                    │
│     - Previous iteration stdout/stderr                      │
│                                                             │
│   What it DOES NOT SEE:                                     │
│     - The actual content of `context`                       │
│     - The actual responses from sub-LMs (only via print())  │
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
│   Root LM sees:                                             │
│     "Code executed: ... REPL output: Chunk 0: Found auth    │
│      middleware in /src/auth.py... Chunk 1: No auth..."     │
│                                                             │
│   Root LM writes more code or calls FINAL(answer)          │
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

The context is loaded into a **Python variable** in the REPL, not into the LM's conversation. The root LM only sees metadata:

```python
# prompts.py, line 158
metadata_prompt = f"Your context is a {context_type} with {context_total_length} total characters,
                    and is broken up into chunks of char lengths: {context_lengths}."
```

The root LM never reads the data. It writes code that *accesses* the data:

```python
# Root LM's output (it's writing a program, not reading data)
chunk = context[0:3]
results = llm_query_batched([f"Analyze: {c}" for c in chunk])
```

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

### The "Evaluation" Is Just Code Execution

The root LM knows it's doing well because:

1. **Code either works or throws** — stderr shows tracebacks, the model self-corrects
2. **print() shows intermediate results** — the model reads its own output and decides next steps
3. **Variables accumulate** — each iteration builds on previous computations
4. **The model decides when it's done** — it calls `FINAL()` or `FINAL_VAR()` when satisfied

This is the same feedback loop a human programmer uses. You don't need a reward function when you can just run the code and see if it worked.

---

## 4. Why Delegating the "Deciding" to Sub-LMs is the Key Move

### The Root LM is a Programmer, Not a Reader

Here's the critical asymmetry:

| | Root LM | Sub-LMs |
|---|---|---|
| **Sees the data** | No (only metadata + print output) | Yes (full chunks) |
| **Writes code** | Yes (the whole point) | No (just answers) |
| **Makes strategy decisions** | Yes (how to decompose) | No (just executes) |
| **Decides what matters** | No | Yes (extracts, summarizes, judges) |
| **Iterates** | Yes (up to 30 rounds) | No (one-shot via `llm_query`) |

The sub-LMs are the ones actually *reading* and *understanding* the data. The root LM is orchestrating. This separation means:

**The root model scales to arbitrary input sizes** because it never needs to hold the data. It just needs to write code that distributes the data to sub-LMs.

**The sub-LMs produce high-quality answers** because each one gets a focused, bounded input — the exact chunk it needs to analyze, with a clear question.

### Recursive Depth Makes This Even More Powerful

When `max_depth > 1`, sub-LMs get their own REPL loops via `rlm_query()`:

```
Root LM (depth=0, strategist)
  │
  ├─ rlm_query("Analyze auth flow in chunk 12")
  │    │
  │    └─ Child RLM (depth=1, gets its own REPL)
  │         ├─ Iteration 0: explores chunk 12
  │         ├─ Iteration 1: llm_query() to extract details
  │         ├─ Iteration 2: FINAL(detailed analysis)
  │         └─ returns result to parent
  │
  ├─ rlm_query("Analyze token handling in chunk 31")
  │    │
  │    └─ Child RLM (depth=1, gets its own REPL)
  │         ├─ ...same iterative process...
  │         └─ returns result to parent
  │
  └─ Root combines results → FINAL(answer)
```

Each child gets:
- Its own REPL namespace
- Its own iteration budget
- A slice of the parent's time/money budget (`rlm.py:708-736`)
- No knowledge of the parent's broader strategy

This is fractal decomposition. Hard problems get recursively broken down until each leaf sub-problem is simple enough for a one-shot LM call.

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

### Layer 3: User Prompt (the nudge each iteration)

```
"Think step-by-step on what to do using the REPL environment
 (which contains the context) to answer the original prompt: '{question}'.
 Continue using the REPL environment... Your next action:"
```

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

This is the only "reward signal." The root LM reads its own stdout and decides what to do next.

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

## 8. Summary: The Three Brilliant Decisions

1. **Context as variable, not conversation.** The data lives in the REPL namespace, not the LM's context window. The root LM writes code to access it, never reads it directly. This decouples reasoning capacity from data size.

2. **Code as the interface.** Instead of tool-calling or function-calling APIs, the LM writes Python. This gives it loops, conditionals, variables, string manipulation — the full power of a programming language for expressing decomposition strategies.

3. **Sub-LMs as the actual readers.** The root LM is a strategist that never touches the data. Sub-LMs are workers that get focused, bounded inputs. Each layer does what it's best at. The root LM scales to arbitrary input sizes because its job complexity is constant — write a program — regardless of how much data the sub-LMs process.

The result: a system that can process arbitrarily large inputs, iteratively refine its approach based on intermediate results, and naturally parallelize work — all without any training, fine-tuning, or reward modeling. Just an LM writing code in a loop.
