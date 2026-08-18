---
name: agent-memory-en
description: 'Build "Agent Memory" — a universal infrastructure giving any AI agent long-term memory, automatic learning, and self-evolution: cross-session memory, conversation auto-sedimentation (digest), hybrid semantic retrieval (BM25 + vector + Rerank), memory graph, pruning, and encryption. Use this skill when the user asks to implement/reproduce/build a memory system, or needs long-term memory, conversation sedimentation, semantic retrieval, knowledge accumulation, or self-evolution capabilities. Contains the complete implementation spec, key design decisions, and acceptance criteria — a new harness instance can reproduce it step by step from this document alone, no further explanation needed.'
whenToUse: 'User asks to implement a memory system; wants "Agent Memory", a memory/learning/evolution infrastructure, or "five-layer memory"; needs long-term memory, conversation auto-sedimentation, hybrid retrieval (BM25+vector+Rerank), memory pruning & encryption for an agent; or asks to review/improve a memory-system architecture.'
license: MIT
compatibility:
  - Claude
  - DeepSeek Harness
  - OpenAI-compatible agents
metadata:
  license: MIT
  version: 3.0
  origin: From hermes-lite (independent system rebuilt after reviewing Hermes v2.1), renamed to reflect its general-purpose positioning
---

# Agent Memory — Agent Memory / Learning / Evolution Infrastructure (Implementation Spec)

> Formerly named **Hermes Lite** (born from a review and rewrite of the Hermes v2.1 five-layer memory guide). This system has long outgrown "lite Hermes" — it is a general memory, automatic-learning, and self-evolution foundation for **all agents**, hence renamed `agent-memory`. The historical name is kept in the docs for traceability.

## 0. Background & Design Philosophy

This system stems from a review and correction of the "Hermes v2.1 five-layer memory guide". The original guide had 40-50% stub code, fabricated core metrics (recall always returned 95-97%), plaintext-stored passwords, and a YAML that was never loaded. This spec keeps its **design ideas** while everything is implemented as **real, runnable code**.

Core principles (must be followed):
1. **No Execution, No Memory**: `execution_verified` defaults to `False`; unverified memories are pruned after 7 days; the `verify` command confirms manually.
2. **Secrets never hit disk**: passwords/tokens/API keys are auto-redacted to `[已脱敏:type]`; writing the raw value to any file is a defect.
3. **Single source of configuration**: all rooms/mappings/retrieval params live only in `config.yaml`; the code loads it; hardcoded duplicates are forbidden.
4. **No fabricated metrics**: every statistic must be a real count; never output "estimated recall" pinned to a fixed range.
5. **Zero-dependency first**: core capabilities (BM25/storage/pruning) are pure standard library; external services (vector/LLM/Rerank) are pluggable backends with circuit-breaker degradation.

## 1. Target Shape

```
Sediment   digest (LLM summarization preferred / rule-based fallback) + conflict detection
Write      remember (redact → dedup-merge → conflict warning → unverified by default → graph update)
Storage    5 rooms (prefs/decisions/configs/projects/events) + Obsidian Markdown
           + atomic writes + daily auto-backup + optional AES encryption
Retrieve   BM25 (pure Python) → vectors (local hash / siliconflow BGE-M3 / jina v3)
           → RRF fusion → Rerank (BGE-reranker-v2-m3) → hot/cold weighting
Lifecycle  Access tracking + adaptive importance (every 10 accesses +1, cap 10) + prune/archive + critical memories kept forever
Associate  Memory graph (entity ↔ memory, auto-maintained)
Workflow   auto_sediment.py (sediment from session logs) + full CLI
```

## 2. Directory Layout

```
agent-memory/           # Project dir name (matches the reference implementation; no functional impact, can be customized)
├── hermes_lite.py        # Single-file core (CLI + library), all classes here
├── config.yaml           # Single configuration source
├── test_hermes_lite.py   # End-to-end tests (≥78 assertions)
├── test_stress.py        # Stress test (150 memories)
├── auto_sediment.py      # Session logs → auto-sedimentation
├── README.md
└── data/                 # Runtime data (set via --root or $HERMES_LITE_ROOT)
    ├── config.yaml       # Copied into the data root (or loaded by the code)
    ├── .env              # Keys (permissions 0600): JINA_API_KEY / SILICONFLOW_API_KEY / DEEPSEEK_API_KEY
    ├── index.json        # Memory index (access counts, verification flags)
    ├── vectors.json      # Vector cache {"backend": name, "vectors": {id: vec}}
    ├── graph.json        # Memory graph {"entities": {name: {type, memory_ids}}}
    ├── .vector_backend_state.json  # Circuit-breaker state (records remote failures)
    ├── .master_key       # AES master key (auto-generated when ENCRYPT=on, permissions 0600)
    ├── rooms/            # Room descriptions
    ├── store/            # Memory bodies (Obsidian-compatible .md, YAML frontmatter)
    └── backups/          # Prune archives + daily auto-backups
```

## 3. Implementation Steps (execute in order, run tests after each phase)

### Phase 1: Storage layer + Entry layer
- `HermesLite` class: `__init__(root)` creates directories, loads YAML config (`yaml.safe_load`, falls back to embedded defaults), loads index.json.
- `remember(text, category, importance, verified, source)`: **unverified by default**; `_redact()` redacts secrets (regexes in §5/§9.5); `_find_duplicate()` merges into the existing entry when similarity ≥0.85 (max importance, no new entry); `_find_conflicts()` detects opposing assertions; writes store/{id}.md (YAML frontmatter) + index.json; `_invalidate_bm25()`.
- `verify(memory_id)`: sets `execution_verified=True`.
- Memory ID format: `mem_YYYYMMDD_HHMMSS_xxxx`.

### Phase 2: Lifecycle
- Room retention: prefs 365 / decisions 730 / configs 365 / projects 545 / events 90 days (from config.yaml).
- Prune `prune(dry_run)`: critical memories (importance=10) kept forever; unverified 7 days; low-frequency (access <3 and >30 days); expired ones are archived to backups/prune_*.json then deleted. **Must truly find and delete — no stubs.**
- `stats()`: total / room distribution / verified count / hot-cold / avg importance / bytes (all real).
- Atomic writes: temp file + `os.replace`; first write of the day auto-backups (keep 7 copies).

### Phase 3: Retrieval (BM25 + vectors + RRF)
- `tokenize_terms(text)`: ASCII words (lowercased) + Chinese 2/3-grams.
- `BM25Index`: pure Python Okapi BM25 (k1=1.5, b=0.75); `search(query)` returns all docs in descending order; `_keyword_rank` filters by room, hot memories (access_count ≥ threshold) get ×1.1.
- Pluggable vector backends:
  - `LocalHashVectorizer`: zero-dependency fallback, character n-gram MD5 hashing → 2048-dim normalized vectors.
  - `JinaVectorizer` (`https://api.jina.ai/v1/embeddings`, jina-embeddings-v3, 1024-dim, international network).
  - `SiliconFlowVectorizer` (`https://api.siliconflow.cn/v1/embeddings`, BAAI/bge-m3, 1024-dim, mainland-China direct; queries prefixed with "为这个句子生成表示以用于检索相关文章：").
  - Key source: environment variable > `data/.env`; backend selection `HERMES_VECTOR_BACKEND=auto|local|jina|siliconflow`; auto prefers jina (if key present), then siliconflow, then local.
  - **Circuit breaker**: one remote failure → persist to `.vector_backend_state.json` → degrade to local and retry once with local to fill vectors; delete the state file or set the backend explicitly to recover.
  - **Backend-switch cache rebuild**: vectors.json carries a backend tag; switching backends (different dims/semantics) clears the cache and regenerates.
- `recall(query, room, top_k)`: keyword ranking + vector recall (cosine ≥ threshold: local 0.30 / remote 0.35, filtered by room) → `rrf_merge([kw_ids, vec_ids])` fusion. Results include kw_score/vec_score.

### Phase 4: Rerank + Graph + Encryption
- `SiliconFlowReranker` (`https://api.siliconflow.cn/v1/rerank`, BAAI/bge-reranker-v2-m3): re-ranks the top-20 candidates after RRF → top-k; on failure, in-process circuit breaker (`_rerank_ok=False`), base retrieval unaffected; disable with `HERMES_RERANK=off`.
- `GraphStore` (graph.json): `extract_entities()` rule-based extraction (uppercase-initial English words minus a stopword list + version numbers `\d+\.\d+` / `v\d+\.\d+`); incrementally maintained on remember/merge/delete; CLI: `graph` / `graph <entity>` / `graph --rebuild`.
- Encryption (`get_encryption`): with `HERMES_ENCRYPT=on`, Fernet AES encrypts index/vectors/graph; key from `HERMES_MASTER_KEY` or auto-generated `data/.master_key` (0600); store/*.md stays plaintext (redaction already protects); degrades gracefully if cryptography is missing. **Off by default.**

### Phase 5: Auto-sedimentation + Workflow
- `RuleDigester` (zero-dependency fallback): regex extraction of decisions/preferences/configs/projects/events, format "label: value".
- `LLMDigester` (OpenAI-compatible chat completions, default DeepSeek `https://api.deepseek.com`, deepseek-chat): system prompt requires a JSON array output (content/category/importance); secrets must not be output in plaintext; `response_format: json_object`; records `last_usage` (real token cost); falls back to rule-based on failure.
- `HermesLite.digest(text, apply)`: extract → preview → with `--apply`, each item goes through the full remember chain (unverified by default).
- `auto_sediment.py`: parses DSH session logs (`user/message` + `assistant/message` text, skipping reasoning/tool results; `.zstd` decompressed via `zstd -dc`; `--latest` auto-finds the newest session) → digest; `--dry-run` preview / `--apply` writes.

### Phase 6: Tests & Acceptance
- `test_hermes_lite.py`: ≥78 assertions covering: config loading, redaction (plaintext never on disk), dedup-merge, conflict detection, verification principle, pruning (incl. critical memories kept forever), BM25 hits/zero-hits, vector cache / backend switch / circuit breaker, RRF, Rerank breaker, graph, encrypted read/write consistency, digest preview/apply.
- `test_stress.py`: 150 unique-content memories (avoid dedup-merge): write ≤10ms/item, retrieve ≤100ms/query, hit rate 10/10 (**printed reference values, not hard assertions** — see §7.2).
- Acceptance demos: a semantic query with no literal overlap hits the right memory; `grep -r "明文密码" data/` is empty; `prune --dry-run` reports real expired counts.

## 4. CLI Command Reference

```
remember TEXT [--category preference|decision|config|project|event|discussion|idea|general]
                [--importance 1-10] [--verified] [--source S]
recall QUERY [--room R] [--top-k N]        # BM25+vector+RRF+Rerank hybrid retrieval
vsearch QUERY [--top-k N]                  # pure vector retrieval (shows cosine)
verify ID                                  # perform verification
prune [--dry-run] [--room R] [--yes]       # prune (archive+delete; --dry-run counts only; --yes for confirmation prompt)
forget ID [--yes]                          # delete single item (--yes is a compat flag; deletion is immediate)
digest TEXT|--file F [--apply] [--max N] [--verified]   # auto-sedimentation
graph [entity] [--top N] [--rebuild]       # memory graph
stats                                      # real statistics (incl. hot/cold)
rooms                                      # room list
vectors                                    # vector backend status (incl. breaker/Rerank state)
```

## 5. Key Design Decisions (do not omit when reproducing)

| Decision | Rationale |
|---|---|
| Full set of 5 redaction regexes in §9.5, incl. copula "是/为" branches | Measured: with the old regex, "密码是 hunter2" captured only "是" and let the password through; value capture uses `([^\s,，。;；]+)` to avoid swallowing punctuation |
| Dedup-merge threshold 0.85 (SequenceMatcher) | Prevents memory bloat; short contents excluded (len<5) |
| Conflict detection pos/neg regexes in §9.6 | Rule-based is zero-cost; LLM detection is better but calling an API on every write is too expensive |
| BM25 instead of heuristic scoring | More sensitive to term frequency / doc length / rare terms; measurably better discrimination (exact-query score 5→25) |
| RRF fusion (k=60) instead of score weighting | The two score scales differ; rank-based fusion is more robust |
| Vector threshold filtering (0.30/0.35) instead of full recall | Prevents irrelevant queries from being polluted by vector recall |
| Adaptive importance +1 every 10 accesses | Frequently used memories naturally rise; cap 10 preserves critical-memory semantics |
| AES off by default | Threat model: data already redacted + 0600 perms; encryption adds key-loss risk and makes files non-greppable |
| Graph auto-maintained, not used for ranking | With small memory volumes the graph has no network effect; keeping it costs nothing; enhance when scale grows |

## 6. Environment Adaptation (important)

- **Network partitioning**: international APIs (jina/openai/huggingface) may be unreachable; mainland-China services (siliconflow/dashscope/deepseek) reachable. The 3 backends + circuit breaker exist precisely for this.
- **Sandbox**: file writes may be restricted to a designated workspace; the data root must live in a writable area (e.g. `agent-memory/data` under the workspace), set via `$HERMES_LITE_ROOT`.
- **Key security**: all keys go only into `data/.env` (chmod 600); never hardcode into code, never print to any output.
- **Token cost transparency**: each digest run costs ~250 fixed system-prompt tokens + input + output (DeepSeek measured ~490 tokens per run / 5 points); retrieval injects top-5 ≈ 300-1000 tokens/round, and this does NOT grow linearly with total memory volume.

## 7. Acceptance Criteria (all must hold)

1. `python3 test_hermes_lite.py` all pass (≥78).
2. `python3 test_stress.py`: 150 memories, exact query hits. Timing values (write ≤10ms/item, retrieve ≤100ms/query) are **printed reference values, not hard assertions** (to avoid flakiness on slow machines); "10/10 hit rate" means all 10 queries returned results.
3. Demonstrate three things:
   - Semantic retrieval: a query with no literal overlap hits — **requires a remote vector key** (siliconflow/jina); without keys, local hashing only demonstrates lexical approximation (synonyms won't match); state the backend during acceptance.
   - Redaction: after writing "密码是 xxx", `grep -r xxx data/` finds nothing.
   - Lifecycle: unverified memories pruned at 7 days, critical memories kept forever (test assertions).
4. All statistics are real counts (no fabricated metrics).
5. Core functionality works with no third-party libraries beyond the standard library (BM25/storage/retrieval/pruning).

## 8. Reference Implementation

The complete reference implementation for this skill lives in the workspace `agent-memory/` (`hermes_lite.py` single file ~1600 lines, 79 tests, 150-memory stress test all passing). Reproduce from this spec; use the reference only to cross-check extreme details inconsistent with this appendix. After implementing, read `Token节省实测分析报告v2.md` to understand the system's token-cost model.

## 9. Data Formats & Configuration Reference (Appendix — implement exactly)

### 9.1 store/*.md format (Obsidian-compatible, YAML frontmatter)

```markdown
---
id: mem_20260817_033106_ab12
category: decision
room: decisions
importance: 8
execution_verified: true
access_count: 3
last_accessed: 2026-08-17T04:00:00+00:00
source: 对话流自动沉淀
created_at: 2026-08-17T03:31:06+00:00
redacted: password,api_key
---

正文内容（已脱敏）
```

Fixed frontmatter field order: id, category, room, importance, execution_verified, access_count, last_accessed, source, created_at, redacted (redacted only when redaction occurred, comma-separated).

### 9.2 index.json entry schema

```json
{
  "id": "mem_20260817_033106_ab12",
  "content": "脱敏后的记忆文本",
  "category": "decision",
  "room": "decisions",
  "importance": 8,
  "execution_verified": false,
  "access_count": 0,
  "last_accessed": null,
  "source": null,
  "created_at": "2026-08-17T03:31:06+00:00",
  "redacted": []
}
```

index.json top level is an array of entries; writes use atomic write (temp file + os.replace) + daily first-write auto-backup to backups/auto_index.json.YYYYMMDD.bak (keep 7). Prune archive format: `backups/prune_YYYYMMDD_HHMMSS.json` = `{"archived_at": ISO-time, "memories": [full entries...]}`.

### 9.3 config.yaml complete reference values

```yaml
rooms:            # retention in days; display fields name/description/icon can be customized
  prefs: 365      # preferences
  decisions: 730  # decisions
  configs: 365    # configs
  projects: 545   # projects
  events: 90      # events
category_mapping:
  preference: prefs   decision: decisions   config: configs
  project: projects   event: events   discussion: events   idea: events   general: events
retrieval:
  default_top_k: 5    min_score: 0.5    time_decay_days: 90
  weight_importance: 0.4    weight_frequency: 0.5    weight_verified: 0.15
  boost_verified: 1.15    hot_threshold: 5    hot_boost: 1.1
pruning:
  unverified_retention_days: 7    low_frequency_days: 30
  low_frequency_threshold: 3    critical_importance: 10    default_retention_days: 90
security:
  redact_patterns: (see 9.5)
```

> Note: weight_importance/weight_frequency/weight_verified are legacy heuristic params; the actual retrieval path uses BM25+RRF+hot boost+min_score. These weight fields are kept for compatibility but are not used by retrieval.

### 9.4 DSH session log structure (auto_sediment parse target)

```json
{"type":"user/message","seq":5,"time":1786932396089,"data":{"content":[{"type":"text","text":"user message"}]}}
{"type":"assistant/message","seq":6,"time":...,"data":{"message":{"role":"assistant","content":[{"type":"reasoning","text":"reasoning (skip)"},{"type":"text","text":"assistant reply"}]}}}
{"type":"tool/call","seq":7,"time":...,"data":{"name":"bash","arguments":"{\"command\":\"...\"}"}}
{"type":"tool/result","seq":8,"time":...,"data":{"message":{"source":{"kind":"tool"},"content":[{"type":"tool-result","toolCallId":"...","content":[{"type":"text","text":"tool output (skip)"}]}]}}}
```

Extraction rules: `user/message` → `data.content[].text`; `assistant/message` → `data.message.content[]` where `type=="text"` (**skip** `reasoning`); **skip** `tool/call` and `tool/result`. Join as "用户: …\n助手: …", truncate to 8000 chars, feed to digest. `.zstd`-compressed session files are decompressed via `zstd -dc` to stdout before parsing.

### 9.5 Redaction regexes (complete set of 5, label inference)

```python
# pattern → redaction label
r"((?:密码|口令|passwd|password)(?:\s*(?:是|为|[:：=])\s*|\s+))([^\s,，。;；]+)"      # password
r"((?:api[_-]?key|apikey|access[_-]?key|密钥)(?:\s*(?:是|为|[:：=])\s*|\s+))([^\s,，。;；]+)"  # api_key
r"((?:token|secret|授权码)(?:\s*(?:是|为|[:：=])\s*|\s+))([^\s,，。;；]+)"          # token
r"(sk-[A-Za-z0-9_\-]{8,})"                                                        # api_key
r"(Bearer\s+[A-Za-z0-9_\-\.]{10,})"                                               # token
```

Replacement logic: when a prefix capture group (group 1) exists, keep the prefix and replace the value with `[已脱敏:label]`; with no prefix group, replace the whole match with `[已脱敏:label]`. **The decision is based on capture-group count ≥2** (prefix+value patterns) before keeping the prefix; single-group patterns (sk-xxx / Bearer xxx) must be **fully replaced** — ⚠️ an older reference version kept the whole match as the "prefix" causing plaintext leakage (`sk-abc123secret[已脱敏:api_key]`); do NOT copy that logic, follow this appendix (fixed and test-covered). Value capture uses `([^\s,，。;；]+)` (**not** `\S+`, to avoid swallowing Chinese punctuation). Execute top-to-bottom; record each label into the `redacted` field. Critical: **copula forms like "密码是 hunter2" must be redacted** — the `(?:\s*(?:是|为|[:：=])\s*|\s+)` branch covers "密码：x", "密码是 x", and "密码 x".

### 9.6 Conflict-detection regexes

```python
pos = r"(?:决定|选择|采用|使用|选用|用)\s*(?:了|的)?\s*([A-Za-z0-9_\-.]+)"   # positive assertion
neg = r"(?:放弃|不用|弃用|反对|拒绝|移除|取消|停止)\s*(?:了|的)?\s*([A-Za-z0-9_\-.]+)"  # negative assertion
```

New text's neg ∩ old memory's pos (or the reverse) → conflict, output {memory_id, entity, type, content}.

### 9.7 recall scoring details

- Keyword score kw_score = BM25 score (>0 is a candidate); hot memories (access_count ≥ hot_threshold) get ×hot_boost.
- Vector score vec_score = cosine (only enters fusion when ≥ threshold: local 0.30 / remote 0.35, filtered by room).
- Fusion: `rrf_merge([kw_ids, vec_ids], k=60)`.
- display_score = kw_score (when >0) else vec_score×3; drop when kw=0 and vec < min_score/3.
- Each hit updates entry.access_count+=1, last_accessed, `_save_index()`; when access_count % 10 == 0 and importance<10, importance+1.
