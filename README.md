# RLM Repo Query

Clone any GitHub repository and query it using [Recursive Language Models (RLMs)](https://arxiv.org/abs/2512.24601).

Instead of stuffing an entire codebase into a single LLM prompt, RLMs externalize the code as context in a Python REPL environment. The LLM then programmatically examines, chunks, and recursively queries sub-LLMs to build an answer — handling repos far larger than any context window.

## Quick Start

```bash
# Install
uv venv && source .venv/bin/activate
uv pip install -e .

# Set your API key (pick one)
export GEMINI_API_KEY="your-key"          # Gemini (default: gemini-2.5-flash)
# export OPENAI_API_KEY="sk-..."          # OpenAI (default: gpt-4o)
# export ANTHROPIC_API_KEY="sk-ant-..."   # Anthropic (default: claude-sonnet-4-20250514)

# Ask a question about any GitHub repo
rlm-repo pallets/flask -b gemini -q "How does routing work?"
```

## Usage

### CLI

```bash
# One-shot question
rlm-repo streamlit/streamlit -b gemini -q "How does session state work?"

# Interactive mode — keep asking questions
rlm-repo pallets/flask -b gemini

# Use a different backend
rlm-repo streamlit/streamlit -b openai -q "Explain the caching system"
rlm-repo streamlit/streamlit -b anthropic -q "Explain the caching system"

# Pick a specific model
rlm-repo owner/repo -b gemini -m gemini-2.5-pro -q "How does auth work?"

# Query a local repo (no cloning)
rlm-repo /path/to/local/repo -b gemini -q "What does this project do?"

# Deeper recursion for large repos
rlm-repo facebook/react -b gemini --max-depth 2 --max-iterations 30 -q "How does the reconciler work?"
```

### Python API

```python
from rlm_repo import RepoRLM, query_repo

# Full control
repo = RepoRLM(
    repo_url="streamlit/streamlit",
    backend="gemini",
    backend_kwargs={"model_name": "gemini-2.5-flash"},
    verbose=True,
)
answer = repo.query("How does Streamlit handle reruns?")

# One-liner
answer = query_repo("pallets/flask", "How does routing work?", backend="gemini")
```

## How It Works

When you run `rlm-repo facebook/react -b gemini -q "How does the reconciler work?"`, here's what happens:

1. **Clone** — `facebook/react` is expanded to `https://github.com/facebook/react.git` and shallow-cloned to `~/.rlm_repo/clones/react`. If it's already there, cloning is skipped.
2. **Index** — walks the repo, reads all source files (`.py`, `.js`, `.ts`, etc.), and builds a structured context string with the directory tree + every file's contents. Large repos get split into chunks (~100K chars each).
3. **RLM Query** — this is where it gets interesting. Instead of dumping the whole codebase into one LLM prompt, the RLM gives the LLM a Python REPL with the repo loaded as a `context` variable. The LLM then:
   - Writes code to explore and chunk the codebase
   - Calls `llm_query("analyze this chunk...")` to make **sub-LLM calls** on specific parts
   - Reads the results, writes more code, makes more sub-calls
   - Repeats across multiple **iterations** (REPL turns) until it has enough info
   - Returns a final answer

### What `--max-depth` and `--max-iterations` do

- **`--max-iterations`** (default: 20) — how many REPL turns the LLM gets. Each turn it can write code, call sub-LLMs, and read results. More iterations = more thorough analysis, but slower and more API calls.
- **`--max-depth`** (default: 1) — controls **recursive** sub-calls. At depth 1, the root LLM can call sub-LLMs, but those sub-LLMs just answer directly. At depth 2, sub-LLMs also get their own REPL and can make their own sub-sub-calls. Deeper = handles bigger repos, but costs more.

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `-b`, `--backend` | `openai` | LLM backend (`openai`, `anthropic`, `gemini`, `openrouter`, `litellm`) |
| `-m`, `--model` | auto | Model name (defaults per backend: `gpt-4o`, `claude-sonnet-4-20250514`, `gemini-2.5-flash`) |
| `--max-depth` | `1` | Recursion depth (1 = root + sub-calls) |
| `--max-iterations` | `20` | Max REPL iterations |
| `--branch` | default | Git branch to clone |
| `--include-tests` | off | Include test files in the index |
| `--log-dir` | none | Directory to save trajectory logs |
| `--no-verbose` | off | Disable rich debug output |

## References

- Paper: [Recursive Language Models](https://arxiv.org/abs/2512.24601) (Zhang, Kraska, Khattab — MIT, 2025)
- Library: [github.com/alexzhang13/rlm](https://github.com/alexzhang13/rlm)
