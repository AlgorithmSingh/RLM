"""Clone a git repository to a local directory."""

import os
import shutil
import subprocess


def clone_repo(
    repo_url: str,
    target_dir: str | None = None,
    branch: str | None = None,
    depth: int | None = 1,
) -> str:
    """
    Clone a git repository.

    Args:
        repo_url: Git URL (https or ssh) or GitHub shorthand like "streamlit/streamlit".
        target_dir: Where to clone. If None, uses a temp directory.
        branch: Specific branch to clone. If None, clones default branch.
        depth: Shallow clone depth. Set to None for full clone.

    Returns:
        Path to the cloned repository.
    """
    # Handle GitHub shorthand: "owner/repo" -> "https://github.com/owner/repo.git"
    if "/" in repo_url and "://" not in repo_url and not repo_url.startswith("git@"):
        repo_url = f"https://github.com/{repo_url}.git"

    if target_dir is None:
        # Extract repo name for a readable cache dir
        repo_name = repo_url.rstrip("/").rstrip(".git").split("/")[-1]
        cache_dir = os.path.join(os.path.expanduser("~"), ".rlm_repo", "clones")
        os.makedirs(cache_dir, exist_ok=True)
        target_dir = os.path.join(cache_dir, repo_name)

    # If already cloned, return existing path
    if os.path.isdir(os.path.join(target_dir, ".git")):
        print(f"Repository already cloned at {target_dir}")
        return target_dir

    # Clean up partial clones
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)

    cmd = ["git", "clone"]
    if depth is not None:
        cmd += ["--depth", str(depth)]
    if branch:
        cmd += ["--branch", branch]
    cmd += [repo_url, target_dir]

    print(f"Cloning {repo_url} ...")
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    print(f"Cloned to {target_dir}")
    return target_dir
