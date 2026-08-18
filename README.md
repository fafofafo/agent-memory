# Agent Memory

> Universal memory / learning / evolution infrastructure for AI agents.
> Cross-session memory · conversation auto-sedimentation · hybrid semantic retrieval · memory graph

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
[![CI](https://github.com/<your-user>/agent-memory/actions/workflows/ci.yml/badge.svg)](https://github.com/<your-user>/agent-memory/actions/workflows/ci.yml)
![Tests](https://img.shields.io/badge/tests-79%20passed-green)
![Stress](https://img.shields.io/badge/stress-150%20memories%20OK-green)

**Agent Memory** gives any AI agent a human-like memory: **remember** (storage), **learn** (auto-sedimentation), **recall** (hybrid retrieval), and **evolve** (adaptive importance, pruning, graph). Deploy once — every agent benefits forever.

Formerly *Hermes Lite*, rebuilt from scratch after reviewing the Hermes v2.1 guide (40-50% stub code, fabricated metrics, plaintext password storage). This is an **independent, fully runnable implementation**.

---

## ✨ Features

| Layer | Capability |
|---|---|
| **Sediment** | Conversation auto-sedimentation via `digest` — LLM summarization (DeepSeek) with rule-based fallback; conflict detection |
| **Write** | `remember` pipeline: secret redaction → dedup-merge → conflict warning → unverified-by-default → graph update |
| **Storage** | 5 topic rooms + Obsidian-compatible Markdown + atomic writes + daily auto-backup + optional AES encryption |
| **Retrieve** | Four-layer hybrid retrieval: **BM25 → semantic vectors → RRF fusion → Rerank re-ranking** |
| **Lifecycle** | Access tracking · adaptive importance (+1 per 10 accesses) · pruning/archive · critical memories kept forever |
| **Associate** | Memory graph — entity ↔ memory, auto-maintained |
| **Security** | Secrets auto-redacted (never stored in plaintext, incl. standalone tokens) · 0600 key permissions · optional Fernet AES |

**No fabricated metrics.** Every statistic is a real count.

## 🧰 Zero heavy dependencies

Core capabilities (BM25 retrieval, storage, pruning, redaction, conflict detection) are **pure Python standard library**. External services (vector embeddings, LLM summarization, Rerank) are pluggable backends with automatic circuit-breaker degradation:

| Backend | Service | Network | Key |
|---|---|---|---|
| Vector | SiliconFlow `BAAI/bge-m3` (1024d) | mainland-China direct | `SILICONFLOW_API_KEY` |
| Vector | Jina `jina-embeddings-v3` (1024d) | international | `JINA_API_KEY` |
| Vector | Local hash (fallback) | offline | — |
| Rerank | SiliconFlow `BAAI/bge-reranker-v2-m3` | mainland-China direct | same `SILICONFLOW_API_KEY` |
| LLM digest | DeepSeek `deepseek-chat` | mainland-China direct | `DEEPSEEK_API_KEY` |

Any service failure degrades gracefully — the system never crashes.

## 🚀 Quick Start

```bash
git clone <your-repo-url> && cd agent-memory

# Option 1: run the reference implementation directly
python3 hermes_lite.py --help
export HERMES_LITE_ROOT=./data && mkdir -p $HERMES_LITE_ROOT
cp config.yaml $HERMES_LITE_ROOT/

# write a memory (unverified by default — No Execution, No Memory)
python3 hermes_lite.py remember "Decided to use PostgreSQL as the production database, port 5432" \
    --category decision --importance 8 --verified

# four-layer hybrid retrieval
python3 hermes_lite.py recall "database choice"

# auto-sediment from a conversation (LLM summarization)
python3 auto_sediment.py --apply

# memory graph
python3 hermes_lite.py graph PostgreSQL

# run the test suite
python3 test_hermes_lite.py    # 79 assertions
python3 test_stress.py         # 150-memory stress test
```

### Option 2: use as a Skill (agent self-implements)

The `skills/` directory contains complete, self-contained implementation specs:

| Skill | Language | Platform |
|---|---|---|
| `skills/agent-memory/` | 中文 | DeepSeek Harness (`~/.dsh/skills/`) |
| `skills/agent-memory-en/` | English | Claude (`~/.claude/skills/`) · DSH |

A fresh agent loads the spec and reproduces the entire system — no further explanation needed.

## 🔑 Keys & Configuration

Keys go into `data/.env` (chmod 600) or environment variables. Full checklist: see [docs/AgentMemory-Dependencies.md](docs/AgentMemory-Dependencies.md) / [docs/AgentMemory-依赖清单.md](docs/AgentMemory-依赖清单.md).

```bash
# data/.env (example)
DEEPSEEK_API_KEY=sk-xxxx        # LLM digest (optional; rule-based fallback otherwise)
SILICONFLOW_API_KEY=sk-xxxx     # vector + rerank (optional; local-hash fallback)
JINA_API_KEY=jina_xxxx          # vector, international (optional)
```

## 📊 Performance & Token Savings

| Metric | Measured |
|---|---|
| Tests | 79 assertions, all passing |
| Stress | 150 memories: write 6ms/item, retrieve 52ms/query, 10/10 hit rate |
| Token savings | **85.6% (measured) ~ 98% (projected)** on input tokens |
| Sedimentation cost | ~490 tokens per LLM digest run |

## 📚 Documentation

- [Product Overview](docs/AgentMemory-Product-Overview.md) / [产品介绍](docs/AgentMemory-产品介绍.md)
- [Dependencies Checklist](docs/AgentMemory-Dependencies.md) / [依赖清单](docs/AgentMemory-依赖清单.md)
- [Token Savings Analysis](docs/Token节省实测分析报告v2.md)

## 📄 License

[MIT](LICENSE) © 2026 Agent Memory Contributors. Free to use, modify, distribute, and sell.

## 🤝 Contributing

Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Security issues: see [SECURITY.md](SECURITY.md).

---

*Agent Memory · Give every agent the power to remember, learn, and evolve*
