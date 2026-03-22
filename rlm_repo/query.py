"""Query a cloned repository using Recursive Language Models."""

from typing import Any

from rlm import RLM
from rlm.logger import RLMLogger

from rlm_repo.clone import clone_repo
from rlm_repo.index import RepoIndex, index_repo


class RepoRLM:
    """
    High-level interface: clone a repo and query it with an RLM.

    The RLM treats the entire codebase as context in a REPL environment,
    then programmatically examines, decomposes, and recursively queries
    sub-LLMs to answer questions about the code.

    Example:
        repo = RepoRLM("streamlit/streamlit", backend="anthropic",
                        backend_kwargs={"model_name": "claude-sonnet-4-20250514"})
        answer = repo.query("How does Streamlit handle session state?")
        print(answer)
    """

    def __init__(
        self,
        repo_url: str | None = None,
        repo_path: str | None = None,
        branch: str | None = None,
        backend: str = "openai",
        backend_kwargs: dict[str, Any] | None = None,
        max_depth: int = 1,
        max_iterations: int = 20,
        max_file_size: int = 256 * 1024,
        include_tests: bool = False,
        max_chunk_chars: int = 100_000,
        verbose: bool = True,
        log_dir: str | None = None,
    ):
        """
        Args:
            repo_url: Git URL or GitHub shorthand (e.g. "streamlit/streamlit").
            repo_path: Path to an already-cloned repo (alternative to repo_url).
            branch: Branch to clone.
            backend: LLM backend ("openai", "anthropic", "openrouter", etc.).
            backend_kwargs: Backend config, e.g. {"model_name": "gpt-5-nano"}.
            max_depth: RLM recursion depth. 1 = root + sub-LLM calls. 2+ = deeper recursion.
            max_iterations: Max REPL iterations before forcing a final answer.
            max_file_size: Skip files larger than this when indexing.
            include_tests: Whether to include test files in the index.
            max_chunk_chars: Max chars per context chunk for sub-LLM calls.
            verbose: Print rich debug output.
            log_dir: Directory to save trajectory logs (JSONL).
        """
        # Clone or use existing repo
        if repo_path:
            self.repo_path = repo_path
        elif repo_url:
            self.repo_path = clone_repo(repo_url, branch=branch)
        else:
            raise ValueError("Provide either repo_url or repo_path")

        # Index the repository
        self.index: RepoIndex = index_repo(
            self.repo_path,
            max_file_size=max_file_size,
            include_tests=include_tests,
        )
        self.max_chunk_chars = max_chunk_chars

        # Build the context: use chunked list for large repos, single string for small ones
        if self.index.total_chars > max_chunk_chars:
            self.context = self.index.to_context_chunks(max_chunk_chars)
        else:
            self.context = self.index.to_context_string()

        # Set up logger
        self.logger = RLMLogger(log_dir=log_dir) if log_dir else None

        # Store RLM config
        self.backend = backend
        self.backend_kwargs = backend_kwargs or {}
        self.max_depth = max_depth
        self.max_iterations = max_iterations
        self.verbose = verbose

    def query(self, question: str, **kwargs) -> str:
        """
        Ask a question about the repository.

        The RLM gets the full repo as context in a REPL environment, where it can
        programmatically chunk, search, and recursively query sub-LLMs to build
        an answer.

        Args:
            question: Natural language question about the codebase.
            **kwargs: Extra kwargs passed to RLM constructor.

        Returns:
            The RLM's answer as a string.
        """
        rlm = RLM(
            backend=self.backend,
            backend_kwargs=self.backend_kwargs,
            environment="local",
            max_depth=self.max_depth,
            max_iterations=self.max_iterations,
            logger=self.logger,
            verbose=self.verbose,
            **kwargs,
        )

        result = rlm.completion(self.context, root_prompt=question)
        return result.response

    def interactive(self):
        """Start an interactive query session."""
        import os
        repo_name = os.path.basename(self.repo_path)
        print(f"\nRLM Repo Query - {repo_name}")
        print(f"  Files indexed: {len(self.index.files)}")
        print(f"  Total chars: {self.index.total_chars:,}")
        print(f"  Backend: {self.backend} / {self.backend_kwargs.get('model_name', 'default')}")
        print(f"\nType your questions (Ctrl+C to exit):\n")

        while True:
            try:
                question = input(">> ").strip()
                if not question:
                    continue
                if question.lower() in {"exit", "quit", "q"}:
                    break
                answer = self.query(question)
                print(f"\n{answer}\n")
            except KeyboardInterrupt:
                print("\nExiting.")
                break
            except Exception as e:
                print(f"\nError: {e}\n")


def query_repo(
    repo: str,
    question: str,
    backend: str = "openai",
    backend_kwargs: dict[str, Any] | None = None,
    **kwargs,
) -> str:
    """
    One-shot convenience function: clone a repo and ask a question.

    Args:
        repo: Git URL or GitHub shorthand (e.g. "streamlit/streamlit").
        question: Question about the codebase.
        backend: LLM backend.
        backend_kwargs: Backend config.
        **kwargs: Extra args passed to RepoRLM.

    Returns:
        Answer string.
    """
    r = RepoRLM(
        repo_url=repo,
        backend=backend,
        backend_kwargs=backend_kwargs,
        **kwargs,
    )
    return r.query(question)
