"""
Example: Query an already-cloned local repository.

Usage:
    export OPENAI_API_KEY="sk-..."
    python examples/local_repo.py /path/to/your/repo
"""

import sys
from rlm_repo import RepoRLM

if len(sys.argv) < 2:
    print("Usage: python examples/local_repo.py /path/to/repo [question]")
    sys.exit(1)

repo_path = sys.argv[1]
question = sys.argv[2] if len(sys.argv) > 2 else None

repo = RepoRLM(
    repo_path=repo_path,
    backend="openai",
    backend_kwargs={"model_name": "gpt-4o"},
    max_depth=1,
    max_iterations=15,
    verbose=True,
)

if question:
    answer = repo.query(question)
    print("\n=== Answer ===")
    print(answer)
else:
    repo.interactive()
