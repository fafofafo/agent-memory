# Agent Memory — Dependencies & Configuration Checklist

> This checklist covers **every external service (model + key), local dependency, environment variable, and network requirement** needed to run Agent Memory, with the purpose, necessity, and where to obtain each key. **This document contains no real key values.** Keys live in `data/.env` (permissions 0600).

---

## 1. External API Services (Models + Keys)

### 1.1 LLM Summarization — Conversation Auto-Sedimentation (digest)

| Item | Detail |
|---|---|
| **Service** | DeepSeek API (`api.deepseek.com`, mainland-China direct) |
| **Key variable** | `DEEPSEEK_API_KEY` |
| **Model** | `deepseek-chat` (DeepSeek V4 Flash) |
| **Purpose** | digest extracts memory points from conversation text (LLM summarization mode, highest quality) |
| **Necessity** | 🟡 Optional — without a key it automatically falls back to **rule-based extraction** (zero cost, lower quality) |
| **Where to get** | Register at [platform.deepseek.com](https://platform.deepseek.com); pay-per-token |
| **Replaceable by** | Any OpenAI-compatible endpoint via `DIGEST_LLM_BASE_URL` + `DIGEST_LLM_MODEL` (e.g., SiliconFlow, Alibaba DashScope) |

### 1.2 Semantic Vectors — Vector Retrieval (core semantic capability)

| Item | Detail |
|---|---|
| **Service A** | SiliconFlow (`api.siliconflow.cn`, **mainland-China direct**) |
| **Key variable A** | `SILICONFLOW_API_KEY` |
| **Model A** | `BAAI/bge-m3` (1024-dim) |
| **Service B** | Jina AI (`api.jina.ai`, **requires international network**) |
| **Key variable B** | `JINA_API_KEY` |
| **Model B** | `jina-embeddings-v3` (1024-dim) |
| **Purpose** | Embed memory contents + queries → cosine similarity semantic retrieval |
| **Necessity** | 🟡 Optional — without keys it falls back to **local hash vectors** (zero cost, no network, but lexical approximation only; synonyms won't match) |
| **Selection priority** | `auto` mode: Jina → SiliconFlow → local; remote failure triggers automatic **circuit-breaker degradation** to local |
| **Where to get** | [siliconflow.cn](https://siliconflow.cn) free credits on signup; [jina.ai](https://jina.ai) free tier |

### 1.3 Rerank Re-ranking — Final Gate for Retrieval Quality

| Item | Detail |
|---|---|
| **Service** | SiliconFlow rerank API (`api.siliconflow.cn`, mainland-China direct) |
| **Key variable** | **Reuses** `SILICONFLOW_API_KEY` (same key) |
| **Model** | `BAAI/bge-reranker-v2-m3` |
| **Purpose** | Re-ranks the top-20 candidates from BM25+vector recall by relevance, outputs final top-k (filters false positives) |
| **Necessity** | 🟢 Low — disable with `HERMES_RERANK=off`; on failure it auto-skips without affecting base retrieval |

---

## 2. Local Runtime Dependencies

| Dependency | Version | Purpose | Necessity |
|---|---|---|---|
| Python | 3.10+ (tested on 3.12) | Runtime | ✅ Required |
| PyYAML | any | Loads `config.yaml` | 🟡 Optional (falls back to embedded defaults) |
| cryptography | any | Only for AES encryption with `HERMES_ENCRYPT=on` | 🟢 Optional (off by default) |
| zstd CLI | any | Only for `auto_sediment.py` decompressing `.zstd` session logs | 🟢 Optional (can decompress manually) |
| — | — | **Core features have zero third-party dependencies**: BM25 retrieval, storage, pruning, redaction, conflict detection — all Python standard library | ✅ |

---

## 3. Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `HERMES_LITE_ROOT` | `~/.hermes-lite` | Data root directory (memory store location; or use the `--root` flag) |
| `HERMES_VECTOR_BACKEND` | `auto` | Vector backend: `auto` / `local` / `jina` / `siliconflow` |
| `HERMES_RERANK` | `on` | Rerank switch: `on` / `off` |
| `HERMES_ENCRYPT` | `off` | Encryption switch: `on` / `off` |
| `HERMES_MASTER_KEY` | auto-generated | Master encryption key (only when `HERMES_ENCRYPT=on`; auto-generated to `data/.master_key` if unset) |
| `DEEPSEEK_API_KEY` | — | LLM summarization key (see above) |
| `SILICONFLOW_API_KEY` | — | Vector + Rerank key (see above) |
| `JINA_API_KEY` | — | Vector key (international network, see above) |
| `DIGEST_LLM_BASE_URL` | `https://api.deepseek.com` | LLM endpoint override (OpenAI-compatible) |
| `DIGEST_LLM_MODEL` | `deepseek-chat` | LLM model override |

> Keys can be set as environment variables or written to `data/.env` (priority: environment variable > `.env` file).

---

## 4. Network Requirements

| Network Environment | Available Services | Behavior When Unavailable |
|---|---|---|
| Mainland China | ✅ DeepSeek, ✅ SiliconFlow | Jina unreachable → vector auto circuit-breaks to local |
| International | ✅ Jina | — |
| Offline | none | Auto-degradation: local hash vectors + rule-based sedimentation; core features still work |

**Design guarantee**: no external service failure can crash the system — full degradation chains (Jina→SiliconFlow→local; LLM→rule-based; Rerank→skip).

---

## 5. Recommended Deployment Profiles

| Profile | Keys Needed | Capabilities Gained |
|---|---|---|
| **Minimal (zero keys)** | none | Full functionality: BM25 retrieval, storage, pruning, dedup, redaction, rule-based sedimentation, local vectors |
| **Standard (recommended, China)** | `DEEPSEEK_API_KEY` + `SILICONFLOW_API_KEY` | + LLM smart summarization + BGE-M3 semantic vectors + Rerank (**complete capability**) |
| **Full (international)** | above + `JINA_API_KEY` | Semantic vectors can switch to Jina (auto-selected by network) |

---

## 6. Key Security Practices

1. **Only two places**: environment variables or `data/.env` (permissions 0600, `chmod 600`)
2. **Never**: hardcode in code / print to any output / commit to version control
3. **Independent revocation**: the three keys (DeepSeek / SiliconFlow / Jina) are independent — revoke one without affecting the others
4. **This checklist contains no real keys**: obtain them from each platform's console

---

*Agent Memory · Dependencies Checklist v1.0 (corresponds to skill version 3.0 / 79 tests)*
