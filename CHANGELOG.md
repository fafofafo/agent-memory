# Changelog

All notable changes to Agent Memory are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [3.0.0] - 2026-08-17

### Added
- **General-purpose rebranding**: renamed from `hermes-lite` to `agent-memory` — positioned as a universal memory / learning / evolution infrastructure for all agents, not a derivative of any specific system.
- **English skill** (`agent-memory-en`): full implementation spec for international markets; compatible with Claude Skills and the Agent Skills standard (`license`/`compatibility` frontmatter fields).
- **Packaging**: release zip (`AgentMemory-v3.0.zip`), GitHub repo skeleton (README, CI, CONTRIBUTING, SECURITY, CHANGELOG).
- **Product documentation**: product overview + dependency checklist in both Chinese and English.

### Changed
- Spec reference updated to `agent-memory/` directory (was `hermes-lite/`).

## [2.0.0] - 2026-08-17

### Added
- **Conversation workflow**: `auto_sediment.py` — one-command auto-sedimentation from DSH session logs (LLM summarization via DeepSeek, rule-based fallback).
- **Security fix**: standalone token redaction (`sk-*` / `Bearer *`) now fully replaces the match instead of keeping it as a prefix — plaintext leakage eliminated (test-covered).
- **Skill packaging**: SKILL.md with self-contained implementation spec (later audited as fully self-contained).

### Changed
- Test suite expanded to 79 assertions.

## [1.0.0] - 2026-08-17

### Added
- Core five-layer memory system:
  - Entry layer: `remember` (redact → dedup-merge → conflict detection → unverified-by-default), `verify`.
  - Storage: 5 topic rooms (prefs/decisions/configs/projects/events) + Obsidian-compatible Markdown + atomic writes + daily auto-backup.
  - Retrieval: BM25 (pure Python) → pluggable vectors (local hash / SiliconFlow BGE-M3 / Jina v3) with circuit-breaker → RRF fusion → Rerank (BGE-reranker-v2-m3) → hot/cold weighting.
  - Lifecycle: access tracking, adaptive importance, pruning/archive, critical memories kept forever.
  - Association: memory graph (entity ↔ memory).
  - Security: secret redaction, 0600 key permissions, optional Fernet AES encryption.
- Auto-sedimentation: `digest` (LLM + rule-based), `RuleDigester`, `LLMDigester`.
- Tests: 78+ assertions; stress test at 150 memories.
