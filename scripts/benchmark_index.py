"""
Benchmark: measure memos index performance on a real repository.

Usage:
    uv run python scripts/benchmark_index.py --repo /path/to/repo

Outputs:
    Phase timings (parse+insert+embed, resolve, total)
    DB size after indexing
    Cold/warm query latency for find_symbol and semantic_search
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path


def _run_index(repo: str, extra_args: list[str] | None = None) -> dict:
    """Run `memos index` and parse PROFILE output from stderr."""
    cmd = [
        sys.executable, "-m", "memos.cli.main", "index",
        "--path", repo, "--full", "--profile",
    ]
    if extra_args:
        cmd.extend(extra_args)

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=repo, check=False)
    if result.returncode != 0:
        print(f"Index failed:\n{result.stderr}", file=sys.stderr)
        return {}

    profile = {}
    for line in result.stderr.splitlines():
        if line.startswith("PROFILE "):
            parts = line[len("PROFILE "):].split()
            for p in parts:
                key, val = p.split("=", 1)
                if key == "db_size":
                    profile[key] = int(val)
                else:
                    profile[key] = float(val.rstrip("s"))

    profile["stdout"] = result.stdout
    return profile


def _query_find_symbol(repo: str, name: str) -> float:
    """Run `memos query symbol <name>` and return elapsed seconds."""
    cmd = [
        sys.executable, "-m", "memos.cli.main", "query", "symbol", name,
        "--path", repo,
    ]
    t0 = time.perf_counter()
    subprocess.run(cmd, capture_output=True, text=True, cwd=repo, check=False)
    return time.perf_counter() - t0


def _query_semantic_search(repo: str, query: str) -> float:
    """Run a semantic search via HTTP API (requires server) or skip."""
    return 0.0


def main():
    parser = argparse.ArgumentParser(description="Benchmark memos index performance")
    parser.add_argument("--repo", required=True, help="Path to benchmark repo")
    args = parser.parse_args()

    repo = str(Path(args.repo).resolve())
    if not Path(repo).exists():
        print(f"Repository not found: {repo}", file=sys.stderr)
        sys.exit(1)

    # Phase 1: index with --no-embed (parse + insert only)
    print("=== Phase 1: index without embeddings ===")
    r1 = _run_index(repo, ["--no-embed"])
    pi1 = r1.get("parse_insert", 0)
    res1 = r1.get("resolve", 0)
    print(f"  parse+insert: {pi1:.2f}s")
    print(f"  resolve:      {res1:.2f}s")

    # Phase 2: full index with embeddings
    print("=== Phase 2: index with embeddings ===")
    r2 = _run_index(repo)
    pi2 = r2.get("parse_insert", 0)
    embed_t = r2.get("embed", 0)
    res2 = r2.get("resolve", 0)
    total = r2.get("total", 0)
    db_size = r2.get("db_size", 0)
    print(f"  parse+insert: {pi2:.2f}s")
    print(f"  embed:        {embed_t:.2f}s")
    print(f"  resolve:      {res2:.2f}s")
    print(f"  total:        {total:.2f}s")
    print(f"  DB size:      {db_size / 1024 / 1024:.1f} MB")

    # Phase 3: cold vs warm query
    print("=== Phase 3: query latency ===")
    cold = _query_find_symbol(repo, "main")
    warm = _query_find_symbol(repo, "main")
    print(f"  find_symbol 'main' (cold):  {cold:.3f}s")
    print(f"  find_symbol 'main' (warm):  {warm:.3f}s")

    print("\nDone.")


if __name__ == "__main__":
    main()
