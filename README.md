# RLM Repo Query

Clone any GitHub repository and query it using [Recursive Language Models (RLMs)](https://arxiv.org/abs/2512.24601).

Instead of stuffing an entire codebase into a single LLM prompt, RLMs externalize the code as context in a Python REPL environment. The LLM then programmatically examines, chunks, and recursively queries sub-LLMs to build an answer — handling repos far larger than any context window.

## Quick Start

```bash
pip install -e .

# Set your API key
export OPENAI_API_KEY="sk-..."

# CLI: ask a question about any repo
rlm-repo streamlit/streamlit -q "How does session state work?"

# CLI: interactive mode
rlm-repo pallets/flask

# CLI: use Anthropic
rlm-repo streamlit/streamlit -b anthropic -m claude-sonnet-4-20250514 -q "Explain the caching system"

# CLI: use Gemini
export GEMINI_API_KEY="your-key"
rlm-repo pallets/markupsafe -b gemini -q "What does this library do?"
```

## Python API

```python
from rlm_repo import RepoRLM, query_repo

# Full control
repo = RepoRLM(
    repo_url="streamlit/streamlit",
    backend="openai",
    backend_kwargs={"model_name": "gpt-4o"},
    verbose=True,
)
answer = repo.query("How does Streamlit handle reruns?")

# One-liner
answer = query_repo("pallets/flask", "How does routing work?")
```

## How It Works

1. **Clone** — shallow-clones the repo (or uses a local path)
2. **Index** — walks the file tree, reads source files, builds a structured context with directory tree + file contents
3. **RLM Query** — passes the context to an RLM, which:
   - Loads the repo into a REPL `context` variable
   - Writes Python code to chunk and search the codebase
   - Calls `llm_query()` / `llm_query_batched()` on chunks to extract information
   - Iterates, building up an answer across multiple REPL turns
   - Returns a final answer via `FINAL()`

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `-b`, `--backend` | `openai` | LLM backend (`openai`, `anthropic`, `gemini`, `openrouter`, `litellm`) |
| `-m`, `--model` | `gpt-4o` | Model name |
| `--max-depth` | `1` | Recursion depth (1 = root + sub-calls) |
| `--max-iterations` | `20` | Max REPL iterations |
| `--branch` | default | Git branch to clone |
| `--include-tests` | off | Include test files |
| `--log-dir` | none | Save trajectory logs |

## References

- Paper: [Recursive Language Models](https://arxiv.org/abs/2512.24601) (Zhang, Kraska, Khattab — MIT, 2025)
- Library: [github.com/alexzhang13/rlm](https://github.com/alexzhang13/rlm)
