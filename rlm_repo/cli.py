"""CLI entry point for rlm-repo."""

import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="rlm-repo",
        description="Clone a repo and query it with Recursive Language Models (RLMs)",
    )
    parser.add_argument(
        "repo",
        help='Git URL or GitHub shorthand (e.g. "streamlit/streamlit")',
    )
    parser.add_argument(
        "-q", "--question",
        help="Question to ask about the repo. If omitted, starts interactive mode.",
    )
    parser.add_argument(
        "-b", "--backend",
        default="openai",
        choices=["openai", "anthropic", "openrouter", "litellm", "gemini", "minimax", "kimik"],
        help="LLM backend (default: openai)",
    )
    parser.add_argument(
        "-m", "--model",
        default=None,
        help="Model name (e.g. gpt-5-nano, claude-sonnet-4-20250514)",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=1,
        help="RLM recursion depth (default: 1)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=20,
        help="Max REPL iterations (default: 20)",
    )
    parser.add_argument(
        "--branch",
        default=None,
        help="Git branch to clone",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Include test files in the index",
    )
    parser.add_argument(
        "--log-dir",
        default=None,
        help="Directory to save trajectory logs",
    )
    parser.add_argument(
        "--no-verbose",
        action="store_true",
        help="Disable verbose output",
    )

    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    from rlm_repo.query import RepoRLM

    # Resolve backend aliases that route through the OpenAI-compatible client
    actual_backend = args.backend
    backend_kwargs = {}

    if args.backend == "minimax":
        actual_backend = "openai"
        backend_kwargs["base_url"] = "https://api.minimax.io/v1"
        backend_kwargs["api_key"] = os.getenv("MINIMAX_API_KEY")
        backend_kwargs["model_name"] = args.model or "MiniMax-M2.5"
    elif args.backend == "kimik":
        actual_backend = "openai"
        backend_kwargs["base_url"] = "https://api.moonshot.ai/v1"
        backend_kwargs["api_key"] = os.getenv("MOONSHOT_API_KEY")
        backend_kwargs["model_name"] = args.model or "kimi-k2.5"
    else:
        if args.model:
            backend_kwargs["model_name"] = args.model
        elif args.backend == "openai":
            backend_kwargs["model_name"] = "gpt-4o"
        elif args.backend == "anthropic":
            backend_kwargs["model_name"] = "claude-sonnet-4-20250514"
        elif args.backend == "gemini":
            backend_kwargs["model_name"] = "gemini-2.5-flash"

    repo = RepoRLM(
        repo_url=args.repo,
        branch=args.branch,
        backend=actual_backend,
        backend_kwargs=backend_kwargs,
        max_depth=args.max_depth,
        max_iterations=args.max_iterations,
        include_tests=args.include_tests,
        verbose=not args.no_verbose,
        log_dir=args.log_dir,
    )

    if args.question:
        answer = repo.query(args.question)
        print(answer)
    else:
        repo.interactive()


if __name__ == "__main__":
    main()
