"""CLI entry point for rlm-repo."""

import argparse
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
        choices=["openai", "anthropic", "openrouter", "litellm"],
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

    from rlm_repo.query import RepoRLM

    backend_kwargs = {}
    if args.model:
        backend_kwargs["model_name"] = args.model
    elif args.backend == "openai":
        backend_kwargs["model_name"] = "gpt-4o"
    elif args.backend == "anthropic":
        backend_kwargs["model_name"] = "claude-sonnet-4-20250514"

    repo = RepoRLM(
        repo_url=args.repo,
        branch=args.branch,
        backend=args.backend,
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
