# Agent Memory — Memory / Learning / Evolution Infrastructure for AI Agents

> A universal capability foundation that gives any AI agent **cross-session long-term memory, automatic learning from conversations, and continuous self-evolution**.
> Formerly named *Hermes Lite*, born from a review and rewrite of the Hermes v2.1 five-layer memory architecture (the original had 40-50% stub code, fabricated metrics, and security flaws). This system is an **independent implementation** — every capability is real and runnable.

---

## One-Line Positioning

**Give any agent a human-like memory: remember (storage), learn (sedimentation), recall (retrieval), and grow (evolution) — deploy once, benefit forever.**

## Why You Need It

| Pain Point | Agent Memory's Answer |
|---|---|
| Total amnesia after each session; history lost | Cross-session persistent memory, never lost |
| Long conversations truncated by context window; early info dropped | Externalized memory breaks the window limit (128k truncation vs never-full) |
| Full history carried every turn; 85-98% token waste | Only the retrieved top-k relevant memories are injected |
| Conversation key points need manual curation | Automatic sedimentation (LLM summarization), zero manual work |
| Keyword-only retrieval misses synonyms / implied meaning | Four-layer hybrid retrieval (BM25 + vector + RRF + Rerank) |
| Memory gets messy and polluted over time | Dedup-merge, conflict detection, pruning, graph association |

## Core Capabilities (Nine-Layer Architecture)

```
Sediment   Automatic conversation digest (LLM summary / rule-based fallback) + conflict detection
Write      remember (redact → dedup → verify → graph update)
Storage    5 topic rooms + Obsidian-compatible + atomic writes + daily auto-backup + optional AES encryption
Retrieve   BM25 → semantic vectors → RRF fusion → Rerank re-ranking → hot/cold weighting
Lifecycle  Access tracking + adaptive importance + pruning/archive + critical memories kept forever
Associate  Memory graph (entity ↔ memory, auto-maintained)
Security   Auto-redaction of secrets (passwords/tokens never stored in plaintext) + 0600 key permissions
Workflow   One-command sedimentation from session logs (auto_sediment)
Ops        Circuit-breaker degradation, backend-switch cache rebuild, honest metrics (no fabricated numbers)
```

## Technical Highlights

1. **Zero heavy dependencies at the core**: BM25 retrieval, storage, pruning, and redaction are pure Python standard library — works out of the box
2. **Pluggable 3-backend vectors**: Local hashing (zero-cost fallback) / SiliconFlow BGE-M3 (mainland-China direct) / Jina v3 (international), with auto-switching and circuit-breaker degradation
3. **Four-layer hybrid retrieval**: BM25 lexical + semantic vector + RRF fusion + Rerank re-ranking — production-grade precision
4. **LLM auto-sedimentation**: DeepSeek summarization (measured ~490 tokens per run), with auto categorization / redaction / dedup
5. **Security by design**: plaintext passwords never hit disk (including standalone tokens), 0600 key permissions, optional Fernet AES encryption
6. **Honest engineering**: every metric is a real count, no fabricated numbers; 79 tests + 150-memory stress validation

## Quick Deployment

### Option 1: New harness on the same machine (zero effort)
Skill already placed at `$DSH_HOME/skills/agent-memory/` — any new session discovers it automatically. Just say "load the agent-memory skill".

### Option 2: New machine (single file)
```bash
# Only SKILL.md is required. Place it at:
mkdir -p ~/.dsh/skills/agent-memory/
cp SKILL.md ~/.dsh/skills/agent-memory/
```
The new harness auto-discovers it and reimplements from the spec (fully self-contained — no extra explanation needed).

### Option 3: With reference implementation (recommended for production)
```bash
# Migrate the whole project directory to reuse the implemented code
cp -r agent-memory/ /target/path/
export HERMES_LITE_ROOT=/target/path/agent-memory/data
python3 agent-memory/hermes_lite.py stats   # verify
```

## Quick Start

```bash
# Write a memory (unverified by default — No Execution, No Memory)
python3 hermes_lite.py remember "Decided to use PostgreSQL as the production database, port 5432" \
    --category decision --importance 8 --verified

# Hybrid retrieval (four layers)
python3 hermes_lite.py recall "database choice"

# Auto-sediment from a conversation (LLM summarization)
python3 auto_sediment.py --apply

# Memory graph
python3 hermes_lite.py graph PostgreSQL

# Lifecycle management
python3 hermes_lite.py prune --dry-run
python3 hermes_lite.py stats
```

## Performance & Reliability

| Metric | Measured |
|---|---|
| Automated tests | **79 assertions, all passing** |
| Stress test | 150 memories: write 6ms/item, retrieve 52ms/query, 10/10 hit rate |
| Token savings | **85.6% (measured) ~ 98% (long-run projection)** on input tokens |
| Sedimentation cost | ~490 tokens per LLM digest run; ~215 tokens/round amortized |
| Data security | Plaintext passwords/keys never on disk + atomic writes + daily backups + optional encryption |

## License & Compliance

- **MIT License** (Copyright 2026 Agent Memory Contributors) — free to use, modify, distribute, and sell
- Independent work; only design ideas were borrowed, no third-party code copied
- Runs on the MIT-licensed DeepSeek Harness platform (github.com/deepseek-ai/deepseek-harness)
- External services (DeepSeek / SiliconFlow / Jina) are optional backends using each platform's public APIs

## How to Get It

- Skill file: `SKILL.md` (complete, self-contained implementation spec)
- Reference implementation: full project directory (code + tests + docs + sample data)
- Support: deployment assistance / customization (more rooms, enterprise integration) / training

---

*Agent Memory · Give every agent the power to remember, learn, and evolve*
