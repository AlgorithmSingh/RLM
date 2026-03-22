#!/usr/bin/env python3
"""
RLM Analysis — Real Repo Test
==============================
Runs the full RLM pipeline against streamlit/streamlit with deep logging,
then generates a verification report that exercises all 6 hook points.
"""

import json
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from rlm.logger.deep_logger import DeepLogger
from rlm_repo.query import RepoRLM

# ── Config ─────────────────────────────────────────────────────────────────
LOG_DIR = os.path.join(os.path.dirname(__file__), "analysis_logs_repo")
DEEP_LOG_PATH = os.path.join(LOG_DIR, "deep_log.jsonl")
os.makedirs(LOG_DIR, exist_ok=True)

REPO = "streamlit/streamlit"
QUESTION = "Explain the caching system"
MAX_DEPTH = 2
MAX_ITERATIONS = 20


def run():
    # Clear previous deep log
    if os.path.exists(DEEP_LOG_PATH):
        os.remove(DEEP_LOG_PATH)

    DeepLogger.enable(DEEP_LOG_PATH)

    repo = RepoRLM(
        repo_url=REPO,
        backend="openai",
        backend_kwargs={
            "model_name": "MiniMax-M1",
            "api_key": os.getenv("MINIMAX_API_KEY"),
            "base_url": "https://api.minimaxi.chat/v1",
        },
        max_depth=MAX_DEPTH,
        max_iterations=MAX_ITERATIONS,
        verbose=True,
        log_dir=LOG_DIR,
    )

    print(f"\nContext type: {type(repo.context)}")
    if isinstance(repo.context, list):
        print(f"Context chunks: {len(repo.context)}")
        total = sum(len(c) for c in repo.context)
        print(f"Total context chars: {total:,}")
        print(f"Chunk sizes: {[len(c) for c in repo.context[:10]]}{'...' if len(repo.context) > 10 else ''}")
    else:
        print(f"Context chars: {len(repo.context):,}")

    print(f"\nRunning RLM: max_depth={MAX_DEPTH}, max_iterations={MAX_ITERATIONS}")
    print(f"Question: {QUESTION}\n")

    t0 = time.time()
    answer = repo.query(QUESTION)
    elapsed = time.time() - t0

    DeepLogger.disable()

    print(f"\n{'='*70}")
    print(f"RLM COMPLETED in {elapsed:.1f}s — answer length: {len(answer)} chars")
    print(f"{'='*70}\n")

    return answer, elapsed


def load_deep_log():
    entries = []
    with open(DEEP_LOG_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def generate_report(entries, answer, elapsed):
    root_prompts = [e for e in entries if e["hook"] == "root_prompt"]
    llm_queries = [e for e in entries if e["hook"] == "llm_query"]
    llm_batched = [e for e in entries if e["hook"] == "llm_query_batched"]
    rlm_queries = [e for e in entries if e["hook"] == "rlm_query"]
    truncations = [e for e in entries if e["hook"] == "truncation"]
    finals = [e for e in entries if e["hook"] == "final_moment"]

    print("=" * 70)
    print("    ANALYSIS VERIFICATION REPORT — REAL REPO (streamlit/streamlit)")
    print("=" * 70)

    # ── CLAIM 1 ────────────────────────────────────────────────────────────
    print("\nCLAIM 1: Root LM sees the question every iteration")
    print("-" * 55)
    for rp in root_prompts:
        it = rp["iteration"]
        last_user = [m for m in rp["messages"] if m["role"] == "user"]
        has_q = any(QUESTION[:30] in m.get("content", "") for m in last_user)
        print(f"  Iteration {it}: question present? {'YES' if has_q else 'NO'} "
              f"({rp['num_messages']} msgs, {rp['total_chars']:,} chars)")

    # ── CLAIM 2 ────────────────────────────────────────────────────────────
    print(f"\nCLAIM 2: Root LM does NOT see raw context data (initially)")
    print("-" * 55)
    if root_prompts:
        first = root_prompts[0]
        sys_msg = [m for m in first["messages"] if m["role"] == "system"]
        user_msgs = [m for m in first["messages"] if m["role"] == "user"]
        # Pick a distinctive string unlikely to be in system prompt
        markers = ["def ", "import ", "class ", "return "]
        for marker in markers:
            in_sys = any(marker in m.get("content", "")[:5000] for m in sys_msg)
            in_user = any(marker in m.get("content", "") for m in user_msgs)
            print(f"  '{marker.strip()}' in system prompt? {'YES' if in_sys else 'NO'} | "
                  f"in iter-0 user msgs? {'YES' if in_user else 'NO'}")
        if user_msgs:
            meta = user_msgs[0]["content"][:250].replace("\n", " ")
            print(f"  Metadata prompt: \"{meta}\"")

    # ── CLAIM 3 ────────────────────────────────────────────────────────────
    print(f"\nCLAIM 3: Root LM's context accumulates via print()")
    print("-" * 55)
    prev_chars = 0
    for rp in root_prompts:
        it = rp["iteration"]
        nc = rp["num_messages"]
        tc = rp["total_chars"]
        delta = f" (delta: +{tc - prev_chars:,} chars)" if it > 0 else ""
        print(f"  Iteration {it}: {nc} msgs, {tc:,} chars{delta}")
        prev_chars = tc

    # ── CLAIM 4 ────────────────────────────────────────────────────────────
    print(f"\nCLAIM 4: Sub-LMs get focused prompts with actual chunk data")
    print("-" * 55)
    total_sub = len(llm_queries)
    batched_individual = sum(b["count"] for b in llm_batched)
    print(f"  llm_query calls: {total_sub}")
    print(f"  llm_query_batched calls: {len(llm_batched)} ({batched_individual} individual)")
    print(f"  rlm_query calls: {len(rlm_queries)}")

    # Show first few sub-LM calls
    all_calls = []
    for q in llm_queries:
        all_calls.append(("llm_query", q["prompt"], q["response"], q.get("depth", "?")))
    for b in llm_batched:
        for p, r in zip(b["prompts"], b["responses"]):
            all_calls.append(("llm_query_batched", p, r, b.get("depth", "?")))
    for q in rlm_queries:
        all_calls.append(("rlm_query", q["prompt"], q["response"], "?"))

    for i, (kind, prompt, response, depth) in enumerate(all_calls[:6]):
        has_code = any(m in prompt for m in ["def ", "class ", "import ", "return "])
        print(f"\n  Sub-LM call {i} ({kind}, depth={depth}):")
        print(f"    prompt: {len(prompt):,} chars, contains code? {'YES' if has_code else 'NO'}")
        print(f"    first 200 chars: \"{prompt[:200].replace(chr(10), ' ')}\"")
        print(f"    response: {len(response):,} chars")
        print(f"    resp preview: \"{response[:150].replace(chr(10), ' ')}\"")

    if len(all_calls) > 6:
        print(f"\n  ... and {len(all_calls) - 6} more sub-LM calls")

    # Prompt size distribution
    if all_calls:
        sizes = [len(c[1]) for c in all_calls]
        print(f"\n  Sub-LM prompt sizes: min={min(sizes):,}, max={max(sizes):,}, "
              f"avg={sum(sizes)//len(sizes):,}, total={sum(sizes):,}")

    # ── CLAIM 5 ────────────────────────────────────────────────────────────
    print(f"\nCLAIM 5: Truncation happens at 20K chars per code block")
    print("-" * 55)
    if truncations:
        print(f"  Truncation events: {len(truncations)}")
        for i, t in enumerate(truncations[:5]):
            print(f"  Event {i}: original={t['original_length']:,} → "
                  f"truncated={t['truncated_length']:,}, lost={t['chars_lost']:,}")
        if len(truncations) > 5:
            total_lost = sum(t["chars_lost"] for t in truncations)
            print(f"  ... total across all events: {total_lost:,} chars lost")
    else:
        print("  No truncation occurred.")

    # ── CLAIM 6 ────────────────────────────────────────────────────────────
    print(f"\nCLAIM 6: No sufficiency criteria in termination")
    print("-" * 55)
    if finals:
        f = finals[0]
        print(f"  Final iteration: {f['iteration']}")
        print(f"  Detection method: {f['detection_method']}")
        print(f"  Root context at FINAL(): {f['message_history_total_chars']:,} chars, "
              f"{f['message_history_num_messages']} msgs")
        print(f"  Final answer: {f['final_answer_length']:,} chars")
        print(f"  Preview: \"{f['final_answer'][:200].replace(chr(10), ' ')}...\"")

        hist_path = os.path.join(LOG_DIR, "final_moment_history.json")
        with open(hist_path, "w") as fh:
            json.dump(f["message_history"], fh, indent=2)
        print(f"  Full history saved to: {hist_path}")
    else:
        print("  WARNING: No FINAL() captured — may have hit max iterations.")
        if root_prompts:
            last = root_prompts[-1]
            print(f"  Last iteration context: {last['total_chars']:,} chars, {last['num_messages']} msgs")

    # ── CLAIM 7 ────────────────────────────────────────────────────────────
    print(f"\nCLAIM 7: System prompt has no evaluation criteria for termination")
    print("-" * 55)
    if root_prompts:
        sys_msgs = [m for m in root_prompts[0]["messages"] if m["role"] == "system"]
        if sys_msgs:
            sys_text = sys_msgs[0]["content"]
            checks = [
                "evaluate whether", "check if you have enough",
                "verify your answer", "assess completeness",
                "stop when", "sufficient information",
            ]
            for phrase in checks:
                found = phrase.lower() in sys_text.lower()
                print(f"  '{phrase}' in system prompt? {'YES' if found else 'NO'}")

    # ── Summary ────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("SUMMARY STATS")
    print(f"{'='*70}")
    print(f"  Total wall time: {elapsed:.1f}s")
    print(f"  Total iterations: {len(root_prompts)}")
    print(f"  llm_query calls: {total_sub}")
    print(f"  llm_query_batched calls: {len(llm_batched)} ({batched_individual} individual)")
    print(f"  rlm_query calls: {len(rlm_queries)}")
    print(f"  Total sub-LM calls: {total_sub + batched_individual + len(rlm_queries)}")
    print(f"  Truncation events: {len(truncations)}")
    print(f"  FINAL() events: {len(finals)}")
    if root_prompts:
        print(f"  Final root context: {root_prompts[-1]['total_chars']:,} chars, "
              f"{root_prompts[-1]['num_messages']} msgs")
    print(f"  Answer length: {len(answer):,} chars")
    print(f"\n  Logs: {LOG_DIR}/")


if __name__ == "__main__":
    answer, elapsed = run()
    entries = load_deep_log()
    generate_report(entries, answer, elapsed)
