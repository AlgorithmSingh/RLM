#!/usr/bin/env python3
"""
RLM Analysis Verification Test
===============================
Instruments the reference RLM, runs a real query with MiniMax-M1,
and prints a structured report verifying every claim from Analysis.md.
"""

import json
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from rlm import RLM
from rlm.logger import RLMLogger
from rlm.logger.deep_logger import DeepLogger

# ── Config ─────────────────────────────────────────────────────────────────
LOG_DIR = os.path.join(os.path.dirname(__file__), "analysis_logs")
DEEP_LOG_PATH = os.path.join(LOG_DIR, "deep_log.jsonl")
os.makedirs(LOG_DIR, exist_ok=True)

# ── Synthetic context: a fictional distributed system ──────────────────────
# 12 chunks describing different subsystems; the question requires synthesizing
# info from at least 3 chunks (auth, billing, and API gateway).
CONTEXT = [
    # Chunk 0 — Database layer
    "=== SUBSYSTEM: Database Layer ===\n"
    "The platform uses PostgreSQL 15 with read replicas for horizontal scaling. "
    "Connection pooling is handled by PgBouncer with a max pool size of 200. "
    "Schema migrations are managed via Alembic. The main tables are: users, "
    "sessions, invoices, subscriptions, api_keys, rate_limits, audit_log. "
    "Row-level security (RLS) is enabled on the users and invoices tables, "
    "ensuring tenant isolation. The sessions table stores session tokens with "
    "a TTL of 24 hours, and expired sessions are cleaned by a cron job every 6 hours.",

    # Chunk 1 — Authentication service
    "=== SUBSYSTEM: Authentication Service ===\n"
    "Auth is handled by a dedicated microservice (auth-svc) running on port 8443. "
    "It supports three authentication methods:\n"
    "1. JWT Bearer Tokens — issued on login, signed with RS256, 15-minute expiry. "
    "Refresh tokens are stored in HTTP-only cookies with a 7-day TTL.\n"
    "2. API Key Authentication — for machine-to-machine calls. API keys are "
    "SHA-256 hashed before storage. Each key has scopes (read, write, admin) "
    "and a rate limit tier.\n"
    "3. OAuth2/OIDC — supports Google and GitHub as identity providers. "
    "The auth-svc acts as a relying party, exchanging authorization codes "
    "for internal JWTs.\n"
    "All auth decisions are logged to the audit_log table with: timestamp, "
    "user_id, action, ip_address, and result (allow/deny).",

    # Chunk 2 — API Gateway
    "=== SUBSYSTEM: API Gateway ===\n"
    "The API gateway (Kong-based) sits at the edge and handles: TLS termination, "
    "request routing, rate limiting, and auth token validation. Rate limits are "
    "enforced per API key tier: free=100req/min, pro=1000req/min, enterprise=10000req/min. "
    "The gateway validates JWT signatures using the auth-svc's public key (JWKS endpoint). "
    "If a token is expired, it returns 401 with a Retry-After header. "
    "Request logging captures: method, path, status code, latency, and user_id "
    "(extracted from the JWT claims). The gateway also implements circuit breaking "
    "for downstream services with a 50% error threshold over a 60-second window.",

    # Chunk 3 — Billing service
    "=== SUBSYSTEM: Billing Service ===\n"
    "Billing is managed by billing-svc which integrates with Stripe. "
    "Subscription tiers: free, pro ($29/mo), enterprise (custom pricing). "
    "Usage-based billing tracks API call counts per billing period. "
    "The billing service authenticates internal calls using the API key mechanism "
    "(with admin scope required). Invoice generation runs on the 1st of each month. "
    "The service exposes /billing/usage endpoint which requires a valid JWT with "
    "'billing:read' scope. Webhook events from Stripe are verified using the "
    "webhook signing secret. Failed payments trigger a 3-day grace period before "
    "account suspension. Suspended accounts retain read-only API access for 30 days.",

    # Chunk 4 — Notification system
    "=== SUBSYSTEM: Notification System ===\n"
    "Notifications are sent via a message queue (RabbitMQ). Event types: "
    "account_created, password_reset, invoice_generated, payment_failed, "
    "usage_threshold_80pct, usage_threshold_100pct, account_suspended. "
    "Email delivery uses SendGrid with template IDs. SMS is via Twilio. "
    "Push notifications use Firebase Cloud Messaging. Each notification has "
    "a delivery status tracked in the notifications table. Retry policy: "
    "3 attempts with exponential backoff (1min, 5min, 30min).",

    # Chunk 5 — Search service
    "=== SUBSYSTEM: Search Service ===\n"
    "Full-text search is powered by Elasticsearch 8.x. Indices: documents, "
    "users, audit_logs. The search API requires authentication (JWT or API key). "
    "Search results are filtered by tenant_id extracted from the auth token, "
    "ensuring data isolation. Indexing is done asynchronously via a Kafka consumer "
    "that processes change events from PostgreSQL's logical replication. "
    "The search service has its own rate limit: 50 queries/sec per tenant.",

    # Chunk 6 — Deployment infrastructure
    "=== SUBSYSTEM: Deployment Infrastructure ===\n"
    "All services run on Kubernetes (EKS). CI/CD pipeline: GitHub Actions → "
    "Docker build → ECR push → ArgoCD GitOps deploy. Each service has: "
    "liveness probe (/healthz), readiness probe (/readyz), and resource limits "
    "(CPU: 500m-2000m, memory: 256Mi-1Gi). Horizontal Pod Autoscaler scales "
    "based on CPU utilization (target: 70%). Secrets are managed via AWS Secrets "
    "Manager and injected as environment variables via External Secrets Operator.",

    # Chunk 7 — Monitoring and observability
    "=== SUBSYSTEM: Monitoring & Observability ===\n"
    "Metrics: Prometheus + Grafana. Key dashboards: request latency (p50/p95/p99), "
    "error rates by service, database connection pool utilization, queue depths. "
    "Logging: structured JSON logs → Fluentd → Elasticsearch → Kibana. "
    "Tracing: OpenTelemetry → Jaeger. All services propagate trace context via "
    "W3C Trace-Context headers. Alerting: PagerDuty integration with escalation "
    "policies. Critical alerts: error rate > 5%, p99 latency > 2s, DB connections > 80%.",

    # Chunk 8 — Data pipeline
    "=== SUBSYSTEM: Data Pipeline ===\n"
    "Analytics data flows: PostgreSQL → Debezium CDC → Kafka → Spark Streaming → "
    "data warehouse (Redshift). ETL jobs run hourly for aggregations. "
    "The pipeline processes ~50M events/day. Data retention: raw events 90 days, "
    "aggregated data 2 years. PII is scrubbed before warehouse ingestion. "
    "The pipeline service uses service-account API keys (admin scope) to "
    "authenticate against the platform APIs.",

    # Chunk 9 — File storage
    "=== SUBSYSTEM: File Storage ===\n"
    "User uploads go to S3 with server-side encryption (AES-256). "
    "Pre-signed URLs (15-minute expiry) are generated by the API for downloads. "
    "File metadata is stored in PostgreSQL. Max file size: 100MB. "
    "Supported types: PDF, DOCX, XLSX, CSV, PNG, JPG. A virus scan (ClamAV) "
    "runs on upload before the file is made available. CDN (CloudFront) "
    "is used for static assets and frequently accessed files.",

    # Chunk 10 — Admin panel
    "=== SUBSYSTEM: Admin Panel ===\n"
    "The admin panel is a React SPA served by nginx. Authentication requires "
    "admin-scoped JWT tokens. Features: user management (CRUD, suspend, "
    "impersonate), subscription management, system health dashboard, "
    "audit log viewer (searchable by user/action/date range), and "
    "feature flag management (LaunchDarkly integration). Admin actions "
    "are double-logged: once in the audit_log table and once to a separate "
    "admin_actions S3 bucket for compliance.",

    # Chunk 11 — Compliance and security
    "=== SUBSYSTEM: Compliance & Security ===\n"
    "SOC 2 Type II certified. GDPR compliance: data deletion requests processed "
    "within 72 hours via a background job that cascades across all services. "
    "Encryption: TLS 1.3 in transit, AES-256 at rest. WAF (AWS WAF) rules "
    "block SQL injection, XSS, and known bad IPs. Security headers: CSP, "
    "HSTS, X-Frame-Options: DENY. Penetration testing: annual via third party. "
    "Vulnerability scanning: Snyk (dependencies) + Trivy (container images), "
    "run on every PR. Incident response plan: documented, tested quarterly. "
    "Auth tokens (JWT) include tenant_id claim to prevent cross-tenant access.",
]

ROOT_PROMPT = (
    "How does the platform handle authentication and authorization across its "
    "different subsystems? Specifically: (1) What authentication methods are "
    "supported? (2) How do internal services authenticate with each other? "
    "(3) How are rate limits enforced per authentication tier? "
    "(4) What happens to API access when a payment fails?"
)


def run_rlm():
    """Run the RLM with deep logging enabled."""
    deep = DeepLogger.enable(DEEP_LOG_PATH)

    rlm = RLM(
        backend="openai",
        backend_kwargs={
            "model_name": "MiniMax-M1",
            "api_key": os.getenv("MINIMAX_API_KEY"),
            "base_url": "https://api.minimaxi.chat/v1",
        },
        environment="local",
        max_depth=1,
        max_iterations=10,
        logger=RLMLogger(log_dir=LOG_DIR),
        verbose=True,
    )

    result = rlm.completion(prompt=CONTEXT, root_prompt=ROOT_PROMPT)
    DeepLogger.disable()
    return result


def load_deep_log():
    """Load all deep log entries."""
    entries = []
    with open(DEEP_LOG_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def generate_report(entries):
    """Generate the verification report from deep log entries."""
    root_prompts = [e for e in entries if e["hook"] == "root_prompt"]
    llm_queries = [e for e in entries if e["hook"] == "llm_query"]
    llm_batched = [e for e in entries if e["hook"] == "llm_query_batched"]
    rlm_queries = [e for e in entries if e["hook"] == "rlm_query"]
    truncations = [e for e in entries if e["hook"] == "truncation"]
    finals = [e for e in entries if e["hook"] == "final_moment"]

    print("=" * 70)
    print("           ANALYSIS VERIFICATION REPORT")
    print("=" * 70)

    # ── CLAIM 1: Root LM sees the question every iteration ─────────────
    print("\nCLAIM 1: Root LM sees the question every iteration")
    print("-" * 55)
    for rp in root_prompts:
        it = rp["iteration"]
        # Check if root_prompt text appears in the last user message
        last_user = [m for m in rp["messages"] if m["role"] == "user"]
        has_question = any(ROOT_PROMPT[:60] in m.get("content", "") for m in last_user)
        last_content = last_user[-1]["content"] if last_user else "(none)"
        preview = last_content[:120].replace("\n", " ")
        print(f"  Iteration {it}: root_prompt present? {'YES' if has_question else 'NO'}")
        print(f"    last user msg preview: \"{preview}...\"")

    # ── CLAIM 2: Root LM does NOT see raw context data ─────────────────
    print(f"\nCLAIM 2: Root LM does NOT see raw context data (only metadata)")
    print("-" * 55)
    if root_prompts:
        first = root_prompts[0]
        sys_msg = [m for m in first["messages"] if m["role"] == "system"]
        user_msgs = [m for m in first["messages"] if m["role"] == "user"]

        # Check if any raw chunk content appears in iteration 0
        sample_chunk_text = "auth-svc"  # distinctive text from chunk 1
        sys_has_raw = any(sample_chunk_text in m.get("content", "") for m in sys_msg)
        iter0_has_raw = any(sample_chunk_text in m.get("content", "") for m in user_msgs)

        print(f"  System prompt contains raw chunk data ('{sample_chunk_text}')? {'YES' if sys_has_raw else 'NO'}")
        print(f"  Iteration 0 user messages contain raw chunk data? {'YES' if iter0_has_raw else 'NO'}")

        # Show metadata prompt
        if len(user_msgs) >= 1:
            meta_preview = user_msgs[0]["content"][:200].replace("\n", " ")
            print(f"  Metadata prompt: \"{meta_preview}\"")

    # ── CLAIM 3: Root LM context accumulates sub-LM responses via print()
    print(f"\nCLAIM 3: Root LM's context accumulates sub-LM responses via print()")
    print("-" * 55)
    for rp in root_prompts:
        it = rp["iteration"]
        nc = rp["num_messages"]
        tc = rp["total_chars"]
        prev = root_prompts[rp["iteration"] - 1] if rp["iteration"] > 0 else None
        delta = f" (delta: +{tc - prev['total_chars']} chars)" if prev else ""
        print(f"  Iteration {it}: {nc} messages, {tc:,} chars{delta}")

    # Check if sub-LM response text appears in later root prompts
    if llm_queries and len(root_prompts) > 1:
        # Take a snippet from the first sub-LM response
        first_resp = llm_queries[0]["response"][:80]
        snippet = first_resp[:40]
        found_in_later = False
        for rp in root_prompts[1:]:
            full_context = " ".join(m.get("content", "") for m in rp["messages"])
            if snippet in full_context:
                found_in_later = True
                break
        print(f"  Sub-LM response text visible in later root context? {'YES' if found_in_later else 'NO'}")
        print(f"    Searched for snippet: \"{snippet}...\"")

    # ── CLAIM 4: Sub-LMs get focused prompts with actual chunk data ────
    print(f"\nCLAIM 4: Sub-LMs get focused prompts with actual chunk data")
    print("-" * 55)
    all_sub_calls = llm_queries + [
        {"prompt": p, "response": r, "prompt_length": len(p), "response_length": len(r)}
        for batch in llm_batched
        for p, r in zip(batch["prompts"], batch["responses"])
    ]
    for i, call in enumerate(all_sub_calls[:8]):  # show first 8
        p = call.get("prompt", "")
        has_chunk = any(marker in p for marker in ["SUBSYSTEM:", "auth-svc", "PostgreSQL", "billing-svc", "Kong"])
        print(f"  Sub-LM call {i}: prompt={call.get('prompt_length', len(p)):,} chars, "
              f"contains chunk data? {'YES' if has_chunk else 'NO'}")
        preview = p[:200].replace("\n", " ")
        print(f"    first 200 chars: \"{preview}\"")
        print(f"    response length: {call.get('response_length', len(call.get('response', ''))):,} chars")

    # ── CLAIM 5: Truncation happens at 20K chars per code block ────────
    print(f"\nCLAIM 5: Truncation happens at 20K chars per code block")
    print("-" * 55)
    if truncations:
        for t in truncations:
            print(f"  Truncation occurred: original={t['original_length']:,} chars, "
                  f"truncated_to={t['truncated_length']:,} chars, "
                  f"chars_lost={t['chars_lost']:,}")
    else:
        print("  No truncation occurred during this run.")

    # ── CLAIM 6: No sufficiency criteria in termination ────────────────
    print(f"\nCLAIM 6: No sufficiency criteria in termination")
    print("-" * 55)
    if finals:
        f = finals[0]
        print(f"  Final iteration number: {f['iteration']}")
        print(f"  Detection method: {f['detection_method']}")
        print(f"  Root LM context at FINAL() time: {f['message_history_total_chars']:,} chars, "
              f"{f['message_history_num_messages']} messages")
        print(f"  Final answer length: {f['final_answer_length']:,} chars")
        print(f"  Final answer preview: \"{f['final_answer'][:300]}...\"")

        # Dump full message history to file
        hist_path = os.path.join(LOG_DIR, "final_moment_history.json")
        with open(hist_path, "w") as fh:
            json.dump(f["message_history"], fh, indent=2)
        print(f"  Full message_history dump: saved to {hist_path}")
    else:
        print("  WARNING: No FINAL() event captured — RLM may have hit max iterations.")

    # ── CLAIM 7: System prompt has no "evaluate whether you're done" ───
    print(f"\nCLAIM 7: System prompt has no 'evaluate whether you\'re done' instruction")
    print("-" * 55)
    if root_prompts:
        sys_msgs = [m for m in root_prompts[0]["messages"] if m["role"] == "system"]
        if sys_msgs:
            sys_text = sys_msgs[0]["content"]
            # Search for termination-related text
            termination_keywords = ["FINAL", "done", "completed", "finished", "sufficient", "evaluate"]
            print("  Termination-related text in system prompt:")
            for kw in termination_keywords:
                indices = []
                start = 0
                while True:
                    idx = sys_text.lower().find(kw.lower(), start)
                    if idx == -1:
                        break
                    indices.append(idx)
                    start = idx + 1
                if indices:
                    for idx in indices[:2]:  # show up to 2 occurrences
                        snippet = sys_text[max(0, idx - 30):idx + 60].replace("\n", " ")
                        print(f"    '{kw}' at pos {idx}: \"...{snippet}...\"")

            has_eval_criteria = any(phrase in sys_text.lower() for phrase in [
                "evaluate whether", "check if you have enough",
                "verify your answer", "assess completeness",
                "stop when", "sufficient information",
            ])
            print(f"  Contains evaluation criteria? {'YES' if has_eval_criteria else 'NO'}")

    # ── Summary stats ──────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SUMMARY STATS")
    print(f"{'=' * 70}")
    print(f"  Total iterations: {len(root_prompts)}")
    print(f"  Total llm_query calls: {len(llm_queries)}")
    print(f"  Total llm_query_batched calls: {len(llm_batched)} "
          f"({sum(b['count'] for b in llm_batched)} individual prompts)")
    print(f"  Total rlm_query calls: {len(rlm_queries)}")
    print(f"  Truncation events: {len(truncations)}")
    print(f"  FINAL() events: {len(finals)}")
    if root_prompts:
        last = root_prompts[-1]
        print(f"  Final root context size: {last['total_chars']:,} chars, {last['num_messages']} messages")
    print(f"\n  Logs saved to: {LOG_DIR}/")
    print(f"  Deep log: {DEEP_LOG_PATH}")


if __name__ == "__main__":
    print("Running RLM with MiniMax-M1 and deep logging...\n")
    result = run_rlm()
    print("\n\n" + "=" * 70)
    print("RLM COMPLETED — Final answer length:", len(result.response), "chars")
    print("=" * 70 + "\n")

    entries = load_deep_log()
    generate_report(entries)
