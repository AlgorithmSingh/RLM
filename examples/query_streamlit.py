"""
Example: Clone Streamlit and query it with an RLM.

Usage:
    # Set your API key first:
    export OPENAI_API_KEY="sk-..."
    # or for Anthropic:
    export ANTHROPIC_API_KEY="sk-ant-..."

    python examples/query_streamlit.py
"""

from rlm_repo import RepoRLM

# --- Option 1: OpenAI backend ---
repo = RepoRLM(
    repo_url="streamlit/streamlit",
    backend="openai",
    backend_kwargs={"model_name": "gpt-4o"},
    max_depth=1,          # 1 = root LLM + sub-LLM calls (no deeper recursion)
    max_iterations=15,    # max REPL iterations before forcing answer
    include_tests=False,  # skip test files to reduce context size
    verbose=True,         # show rich debug output
)

# --- Option 2: Anthropic backend ---
# repo = RepoRLM(
#     repo_url="streamlit/streamlit",
#     backend="anthropic",
#     backend_kwargs={"model_name": "claude-sonnet-4-20250514"},
#     max_depth=1,
#     max_iterations=15,
#     verbose=True,
# )

# Ask a single question
answer = repo.query("How does Streamlit's session state work? Trace the implementation.")
print("\n=== Answer ===")
print(answer)

# Or start interactive mode:
# repo.interactive()
