"""Index a repository into structured context for RLM consumption."""

import os
from dataclasses import dataclass, field

# Extensions considered source code (readable text files worth indexing)
SOURCE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala", ".r",
    ".sql", ".sh", ".bash", ".zsh", ".fish", ".ps1",
    ".html", ".css", ".scss", ".less", ".sass",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".xml", ".md", ".rst", ".txt", ".csv",
    ".dockerfile", ".makefile", ".cmake",
    ".proto", ".graphql", ".tf", ".hcl",
    ".vue", ".svelte", ".astro",
}

# Files always worth including regardless of extension
IMPORTANT_FILENAMES = {
    "Makefile", "Dockerfile", "Procfile", "Gemfile", "Rakefile",
    "CMakeLists.txt", "docker-compose.yml", "docker-compose.yaml",
    ".env.example", ".gitignore", "LICENSE",
}

# Directories to skip
SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "dist", "build", ".eggs",
    "*.egg-info", "venv", ".venv", "env", ".env",
    ".next", ".nuxt", "coverage", ".coverage",
    "vendor", "third_party", "site-packages",
}

# Max file size to index (256KB) - skip large generated files
MAX_FILE_SIZE = 256 * 1024


@dataclass
class RepoFile:
    """A single indexed file from the repository."""
    path: str          # Relative path from repo root
    content: str       # File content
    size: int          # Size in bytes
    extension: str     # File extension


@dataclass
class RepoIndex:
    """Indexed repository ready for RLM consumption."""
    repo_path: str
    files: list[RepoFile] = field(default_factory=list)
    tree: str = ""     # Directory tree string
    total_chars: int = 0

    def to_context_string(self) -> str:
        """Convert the entire repo index to a single context string."""
        parts = [
            f"# Repository: {os.path.basename(self.repo_path)}",
            f"# Total files indexed: {len(self.files)}",
            f"# Total characters: {self.total_chars:,}",
            "",
            "## Directory Structure",
            self.tree,
            "",
        ]
        for f in self.files:
            parts.append(f"## File: {f.path}")
            parts.append(f"```{f.extension.lstrip('.')}")
            parts.append(f.content)
            parts.append("```")
            parts.append("")
        return "\n".join(parts)

    def to_context_chunks(self, max_chunk_chars: int = 100_000) -> list[str]:
        """Split the repo into chunks suitable for sub-LLM calls.

        Each chunk contains complete files (never splits a file mid-content).
        Includes the directory tree in the first chunk as orientation.
        """
        header = (
            f"# Repository: {os.path.basename(self.repo_path)}\n"
            f"# Total files: {len(self.files)} | Total chars: {self.total_chars:,}\n\n"
            f"## Directory Structure\n{self.tree}\n\n"
        )

        chunks = []
        current = header
        for f in self.files:
            file_block = (
                f"## File: {f.path}\n"
                f"```{f.extension.lstrip('.')}\n"
                f"{f.content}\n"
                f"```\n\n"
            )
            # If adding this file would exceed the limit, start a new chunk
            if len(current) + len(file_block) > max_chunk_chars and current != header:
                chunks.append(current)
                current = f"# Repository: {os.path.basename(self.repo_path)} (continued)\n\n"
            current += file_block

        if current.strip():
            chunks.append(current)

        return chunks if chunks else [header]

    def to_file_map(self) -> dict[str, str]:
        """Return a dict mapping file paths to their contents."""
        return {f.path: f.content for f in self.files}


def _should_skip_dir(dirname: str) -> bool:
    """Check if a directory should be skipped."""
    return dirname in SKIP_DIRS or dirname.endswith(".egg-info")


def _should_index_file(filename: str) -> bool:
    """Check if a file should be indexed."""
    if filename in IMPORTANT_FILENAMES:
        return True
    _, ext = os.path.splitext(filename)
    return ext.lower() in SOURCE_EXTENSIONS


def _build_tree(repo_path: str, prefix: str = "", max_depth: int = 4, _depth: int = 0) -> str:
    """Build a directory tree string."""
    if _depth > max_depth:
        return prefix + "...\n"

    entries = sorted(os.listdir(repo_path))
    dirs = [e for e in entries if os.path.isdir(os.path.join(repo_path, e)) and not _should_skip_dir(e)]
    files = [e for e in entries if os.path.isfile(os.path.join(repo_path, e))]

    lines = []
    items = dirs + files
    for i, name in enumerate(items):
        is_last = i == len(items) - 1
        connector = "└── " if is_last else "├── "
        full_path = os.path.join(repo_path, name)

        if os.path.isdir(full_path):
            lines.append(f"{prefix}{connector}{name}/")
            extension = "    " if is_last else "│   "
            lines.append(_build_tree(full_path, prefix + extension, max_depth, _depth + 1))
        else:
            lines.append(f"{prefix}{connector}{name}")

    return "\n".join(lines)


def index_repo(
    repo_path: str,
    extensions: set[str] | None = None,
    max_file_size: int = MAX_FILE_SIZE,
    include_tests: bool = True,
) -> RepoIndex:
    """
    Walk a repository and index all source files.

    Args:
        repo_path: Path to the repository root.
        extensions: Override set of file extensions to index. If None, uses defaults.
        max_file_size: Skip files larger than this (bytes).
        include_tests: Whether to include test files.

    Returns:
        RepoIndex with all indexed files and metadata.
    """
    if extensions is None:
        extensions = SOURCE_EXTENSIONS

    index = RepoIndex(repo_path=repo_path)
    index.tree = _build_tree(repo_path)

    for root, dirs, filenames in os.walk(repo_path):
        # Filter out directories we want to skip (modifying dirs in-place)
        dirs[:] = [d for d in dirs if not _should_skip_dir(d)]

        # Optionally skip test directories
        if not include_tests:
            dirs[:] = [d for d in dirs if d not in {"tests", "test", "testing", "spec"}]

        for filename in sorted(filenames):
            if not _should_index_file(filename):
                continue

            filepath = os.path.join(root, filename)
            relpath = os.path.relpath(filepath, repo_path)

            # Skip test files if requested
            if not include_tests and any(
                part in {"tests", "test", "testing", "spec"} for part in relpath.split(os.sep)
            ):
                continue

            # Skip files that are too large
            try:
                file_size = os.path.getsize(filepath)
            except OSError:
                continue
            if file_size > max_file_size:
                continue

            # Read file content
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except (OSError, UnicodeDecodeError):
                continue

            _, ext = os.path.splitext(filename)
            index.files.append(RepoFile(
                path=relpath,
                content=content,
                size=file_size,
                extension=ext,
            ))
            index.total_chars += len(content)

    print(f"Indexed {len(index.files)} files ({index.total_chars:,} chars) from {repo_path}")
    return index
