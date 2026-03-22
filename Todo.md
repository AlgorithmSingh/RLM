# RLM TODOs

## 1. Add full prompt/response logging and run a live test to confirm the Analysis

### Background

Read `/Users/ankitsingh/Documents/dev/RLM/RLM/Analysis.md` first. It makes several claims about how the REPL loop works, what the root LM sees, and how termination happens. We need to **empirically verify** these claims by instrumenting the code, running a real query, and inspecting the logs.

### Prerequisites

The MiniMax API key is in `/Users/ankitsingh/Documents/dev/RLM/.env` (gitignored). The RLM library uses `dotenv` so it will be loaded automatically.

MiniMax uses an OpenAI-compatible API. Use the `openai` backend with the MiniMax base URL:

```python
from dotenv import load_dotenv
load_dotenv()

rlm = RLM(
    backend="openai",
    backend_kwargs={
        "model_name": "MiniMax-M1",
        "api_key": os.getenv("MINIMAX_API_KEY"),
        "base_url": "https://api.minimaxi.chat/v1",
    },
    environment="local",
    max_depth=1,
    max_iterations=10,
    logger=RLMLogger(log_dir="./analysis_logs"),
    verbose=True,
)
```

The reference RLM library is at `/Users/ankitsingh/Documents/dev/RLM/reference/rlm`. Install it first:

```bash
cd /Users/ankitsingh/Documents/dev/RLM/reference/rlm && pip install -e .
```

### Step 1: Instrument the code for deep logging

The existing `RLMLogger` (`reference/rlm/rlm/logger/rlm_logger.py`) logs iterations but does NOT capture:
- The full `message_history` (what the root LM's context actually contains)
- The raw prompts sent to sub-LMs (with interpolated context/chunk data)
- The full sub-LM responses before truncation
- The complete context snapshot at the moment FINAL() is called

Add logging at these exact hook points in the reference implementation:

#### Hook 1: Root LM prompt each iteration
**File**: `reference/rlm/rlm/core/rlm.py`, lines 341-343
```python
current_prompt = message_history + [
    build_user_prompt(root_prompt, i, context_count, history_count)
]
```
**Log**: The complete `current_prompt` list — every message (system, user, assistant) the root LM receives. Include the total character count and number of messages.

#### Hook 2: Sub-LM calls (llm_query)
**File**: `reference/rlm/rlm/environments/local_repl.py`, lines 248-270 (`_llm_query`)
```python
request = LMRequest(prompt=prompt, model=model, depth=self.depth)
response = send_lm_request(self.lm_handler_address, request)
```
**Log**: The exact `prompt` string (this contains the interpolated f-string with actual chunk data), the full `response.chat_completion.response`, and which model handled it.

#### Hook 3: Batched sub-LM calls
**File**: `reference/rlm/rlm/environments/local_repl.py`, lines 272-301 (`_llm_query_batched`)
**Log**: All prompts in the batch and all responses, in order.

#### Hook 4: rlm_query sub-calls
**File**: `reference/rlm/rlm/environments/local_repl.py`, lines 303-323 (`_rlm_query`)
**Log**: The prompt sent to the child RLM and the child's final response.

#### Hook 5: Stdout truncation
**File**: `reference/rlm/rlm/utils/parsing.py`, lines 94-98
```python
if len(result) > max_character_length:
    result = result[:max_character_length] + f"... + [{len(result) - max_character_length} chars...]"
```
**Log**: Both the full result (pre-truncation) and the truncated version. Flag when truncation happens and how many chars were lost.

#### Hook 6: FINAL() decision moment
**File**: `reference/rlm/rlm/core/rlm.py`, lines 356-365 (where `final_answer` is detected) and line 378 (where it's confirmed non-None)
**Log**: Dump the complete `message_history` at this moment. This is the full picture of what the root LM had seen when it decided to stop. Also log whether it was detected via REPL (`FINAL_VAR` in code) or via text regex (`FINAL()` in response).

### Step 2: Write and run the test script

Create a test script at `/Users/ankitsingh/Documents/dev/RLM/RLM/analysis_test.py` that:

1. Creates a non-trivial context — something with multiple chunks where the answer requires synthesizing info from different parts (not just a needle-in-haystack). For example:
   - A list of 10+ text chunks describing different parts of a fictional system
   - A question that requires finding info across at least 3 chunks to answer fully

2. Runs the RLM with MiniMax-M1 and full logging enabled

3. After completion, reads the logs and prints a structured report:

```
=== ANALYSIS VERIFICATION REPORT ===

CLAIM 1: Root LM sees the question every iteration
  Iteration 0: root_prompt present? YES/NO — actual text: "..."
  Iteration 1: root_prompt present? YES/NO — actual text: "..."
  ...

CLAIM 2: Root LM does NOT see raw context data (only metadata)
  System prompt contains raw data? YES/NO
  Metadata prompt: "Your context is a ... with N total characters..."
  First iteration prompt contains chunk content? YES/NO

CLAIM 3: Root LM's context accumulates sub-LM responses via print()
  Iteration 0 context size: N chars, M messages
  Iteration 1 context size: N chars, M messages (delta: +X chars)
  Iteration 2 context size: N chars, M messages (delta: +X chars)
  Sub-LM response text visible in root context? YES/NO
  Example: "REPL output: [first 200 chars of what root LM saw]..."

CLAIM 4: Sub-LMs get focused prompts with actual chunk data
  Sub-LM call 1: prompt length = N chars, contains chunk data? YES/NO
  Sub-LM call 1: first 200 chars of prompt: "..."
  Sub-LM call 1: response length = N chars

CLAIM 5: Truncation happens at 20K chars per code block
  Any truncation occurred? YES/NO
  If yes: original length vs truncated length, chars lost

CLAIM 6: No sufficiency criteria in termination
  Final iteration number: N
  Detection method: FINAL_VAR in REPL / FINAL() in text
  Root LM context at FINAL() time: N chars, M messages
  Full message_history dump: [saved to file]

CLAIM 7: System prompt has no "evaluate whether you're done" instruction
  Termination-related text in system prompt: "[exact text]"
  Contains evaluation criteria? YES/NO
```

4. Save the full logs to `./analysis_logs/` and the report to stdout

### Step 3: Update the Analysis based on findings

Based on the actual logs:

1. **Update** `/Users/ankitsingh/Documents/dev/RLM/RLM/Analysis.md` with real data:
   - Replace hypothetical examples with actual logged prompts/responses
   - Correct any claims that turn out to be wrong
   - Add the actual context sizes observed at each iteration
   - Show what truncation (if any) actually happened
   - Quote the exact root LM context at FINAL() time

2. **Create** `/Users/ankitsingh/Documents/dev/RLM/RLM/AnalysisSummary.md` with:
   - A concise (1-2 page) summary of findings
   - Which claims from Analysis.md were confirmed vs. corrected
   - The actual numbers: context sizes, sub-LM call counts, truncation stats
   - The exact system prompt text around termination (confirming no sufficiency criteria)
   - One concrete example trace: what the root LM saw at each iteration (abbreviated)
   - Key insight: is the FINAL() decision informed or a best guess? What does the log evidence say?

### What we're trying to answer

These are the specific curiosities driving this work:

1. **Does the root LM really never see the raw data?** Or does some of it leak into the context via metadata, print output, or other paths?

2. **How much sub-LM content ends up in the root LM's context?** Is it mostly metadata + summaries, or does it become substantial? At what iteration does the root LM's context start looking "polluted" with actual data?

3. **What does the root LM's context look like at the exact moment it calls FINAL()?** Is it making an informed decision with rich sub-LM analysis in context, or is it working with thin/truncated summaries?

4. **Is 20K chars per code block enough?** Do sub-LM responses get meaningfully truncated? Does the root LM lose important information?

5. **Could the root LM have gotten a better answer with one more iteration?** Did it stop too early? Were there chunks it never queried?

6. **What prompts are actually sent to sub-LMs?** When the root LM writes `f"Analyze: {context[12]}"`, how big is that interpolated string? Does the sub-LM get well-formed input or something mangled?

### Output files

- `./analysis_logs/*.jsonl` — raw JSONL logs from the instrumented run
- `/Users/ankitsingh/Documents/dev/RLM/RLM/Analysis.md` — updated with real data
- `/Users/ankitsingh/Documents/dev/RLM/RLM/AnalysisSummary.md` — concise summary of findings
