"""
Example: One-shot query on any repository.

Usage:
    export OPENAI_API_KEY="sk-..."
    python examples/query_any_repo.py
"""

from rlm_repo import query_repo

# One-liner: clone + index + query
answer = query_repo(
    repo="pallets/flask",
    question="How does Flask's routing system work? Explain the request dispatching flow.",
    backend="openai",
    backend_kwargs={"model_name": "gpt-4o"},
    verbose=True,
)

print("\n=== Answer ===")
print(answer)
