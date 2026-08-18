#!/usr/bin/env python3
"""Agent Memory - 智能体记忆/学习/进化系统（DSH 落地版，原 Hermes Lite）

修正 Hermes v2.1 指南中的关键问题：
  ✅ 真实检索：关键词 + 中文 n-gram 重叠 + 加权打分，无伪造指标
  ✅ 真实淘汰：过期查找 + 归档 + 删除，非空壳
  ✅ 敏感信息脱敏：密码/token/密钥原文不落盘
  ✅ 配置单一来源：YAML 被真正加载，无硬编码副本
  ✅ execution_verified 默认 False：未验证记忆短留（No Execution, No Memory）
  ✅ 单机轻量：去掉虚假的异步同步与未实现的分布式层

用法示例：
  python3 hermes_lite.py remember "决定采用 PostgreSQL，端口 5432" --category decision --importance 8 --verified
  python3 hermes_lite.py recall "数据库端口"
  python3 hermes_lite.py verify mem_20260817_120000_abcd
  python3 hermes_lite.py prune --dry-run
  python3 hermes_lite.py stats
"""

import argparse
import difflib
import hashlib
import json
import math
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

DEFAULT_ROOT = Path.home() / ".hermes-lite"
CONFIG_NAME = "config.yaml"

# 内嵌默认配置（config.yaml 缺失时的兜底，不维护第二份业务配置）
DEFAULT_CONFIG = {
    "rooms": {
        "prefs": {"name": "偏好", "description": "用户偏好设置", "icon": "⭐", "retention_days": 365},
        "decisions": {"name": "决策", "description": "重要决定记录", "icon": "✅", "retention_days": 730},
        "configs": {"name": "配置", "description": "系统配置信息", "icon": "⚙️", "retention_days": 365},
        "projects": {"name": "项目", "description": "项目相关记忆", "icon": "📁", "retention_days": 545},
        "events": {"name": "事件", "description": "对话历史事件", "icon": "📅", "retention_days": 90},
    },
    "category_mapping": {
        "preference": "prefs", "decision": "decisions", "config": "configs",
        "project": "projects", "event": "events", "discussion": "events",
        "idea": "events", "general": "events",
    },
    "retrieval": {
        "default_top_k": 5, "min_score": 0.5, "time_decay_days": 90,
        "weight_importance": 0.4, "weight_frequency": 0.5,
        "weight_verified": 0.15, "boost_verified": 1.15,
        "hot_threshold": 5, "hot_boost": 1.1,
    },
    "pruning": {
        "unverified_retention_days": 7, "low_frequency_days": 30,
        "low_frequency_threshold": 3, "critical_importance": 10,
        "default_retention_days": 90,
    },
    "security": {
        "redact_patterns": [
            r"((?:密码|口令|passwd|password)(?:\s*(?:是|为|[:：=])\s*|\s+))([^\s,，。;；]+)",
            r"((?:api[_-]?key|apikey|access[_-]?key|密钥)(?:\s*(?:是|为|[:：=])\s*|\s+))([^\s,，。;；]+)",
            r"((?:token|secret|授权码)(?:\s*(?:是|为|[:：=])\s*|\s+))([^\s,，。;；]+)",
            r"(sk-[A-Za-z0-9_\-]{8,})",
            r"(Bearer\s+[A-Za-z0-9_\-\.]{10,})",
        ]
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    """递归合并配置：override 覆盖 base。"""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def days_between(iso_a: str, iso_b: str) -> int:
    return max(0, int((parse_iso(iso_b) - parse_iso(iso_a)).total_seconds() // 86400))


# =====================================================================
# 向量检索层（可插拔后端）
#  - LocalHashVectorizer: 零依赖本地兜底（字符 n-gram 哈希，词法近似语义）
#  - JinaVectorizer:      Jina Embeddings v3 API（国际网络，key 存 data/.env）
#  - SiliconFlowVectorizer: 硅基流动 BGE-M3（国内网络，OpenAI 兼容格式）
# 后端选择：环境变量 HERMES_VECTOR_BACKEND=auto|local|jina|siliconflow
# key 优先级：进程环境变量 > data/.env 文件（权限 600）
# =====================================================================


try:
    from cryptography.fernet import Fernet
except ImportError:  # pragma: no cover
    Fernet = None


def get_encryption(root: Path) -> tuple[bool, "Fernet | None"]:
    """读取加密配置。HERMES_ENCRYPT=on 时启用 Fernet AES 加密。

    key 来源：环境变量/.env 的 HERMES_MASTER_KEY，否则自动生成并存入
    data/.master_key（权限 600）。cryptography 未安装时优雅降级为明文。
    """
    if Fernet is None:
        return False, None
    env = load_env_file(root)
    enabled = (os.environ.get("HERMES_ENCRYPT") or env.get("HERMES_ENCRYPT") or "off")
    if enabled.lower() not in ("on", "1", "true", "yes"):
        return False, None
    key = os.environ.get("HERMES_MASTER_KEY") or env.get("HERMES_MASTER_KEY")
    key_path = Path(root) / ".master_key"
    if not key:
        if key_path.exists():
            key = key_path.read_text(encoding="utf-8").strip()
        else:
            key = Fernet.generate_key().decode("ascii")
            key_path.write_text(key, encoding="utf-8")
            try:
                os.chmod(key_path, 0o600)
            except OSError:
                pass
    try:
        return True, Fernet(key.encode("ascii"))
    except Exception:
        return False, None


def maybe_decrypt(raw: str, cipher) -> str:
    if cipher is None:
        return raw
    try:
        return cipher.decrypt(raw.encode("ascii")).decode("utf-8")
    except Exception:
        return raw


def maybe_encrypt(content: str, cipher) -> str:
    if cipher is None:
        return content
    return cipher.encrypt(content.encode("utf-8")).decode("ascii")


def load_env_file(root: Path) -> dict:
    """从 root/.env 加载密钥（静默，不存在返回空）。"""
    env = {}
    env_path = Path(root) / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip()
        except OSError:
            pass
    return env


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def rrf_merge(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion：融合多路排序。"""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda pair: pair[1], reverse=True)


def tokenize_terms(text: str) -> list[str]:
    """检索词元化：ASCII/数字词（小写）+ 中文 2/3-gram。"""
    terms = [t.lower() for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9_\-\.]{1,}", text)]
    chars = re.sub(r"\s+", "", text)
    for n in (2, 3):
        terms.extend(chars[i:i + n] for i in range(len(chars) - n + 1))
    return terms


class BM25Index:
    """纯 Python BM25 检索（零依赖）。

    标准 Okapi BM25：k1=1.5, b=0.75。term 用 tokenize_terms（ASCII 词 + 中文 n-gram），
    比原启发式打分对"词频/文档长度/稀有词"更敏感，检索质量更高。
    """

    K1 = 1.5
    B = 0.75

    def __init__(self, docs: list[str]):
        self.docs = docs
        self.doc_terms: list[dict[str, int]] = []
        self.doc_freq: dict[str, int] = {}
        total_len = 0
        for doc in docs:
            counter: dict[str, int] = {}
            for term in tokenize_terms(doc):
                counter[term] = counter.get(term, 0) + 1
            self.doc_terms.append(counter)
            for term in counter:
                self.doc_freq[term] = self.doc_freq.get(term, 0) + 1
            total_len += sum(counter.values())
        self.n = len(docs)
        self.avgdl = total_len / self.n if self.n else 0.0

    def _idf(self, term: str) -> float:
        n = self.doc_freq.get(term, 0)
        return math.log(1.0 + (self.n - n + 0.5) / (n + 0.5))

    def score(self, query: str, doc_idx: int) -> float:
        dl = sum(self.doc_terms[doc_idx].values())
        if dl == 0 or self.avgdl == 0:
            return 0.0
        score = 0.0
        for term in set(tokenize_terms(query)):
            f = self.doc_terms[doc_idx].get(term, 0)
            if f == 0:
                continue
            idf = self._idf(term)
            norm = f * (self.K1 + 1.0)
            denom = f + self.K1 * (1.0 - self.B + self.B * dl / self.avgdl)
            score += idf * norm / denom
        return score

    def search(self, query: str, top_k: int | None = None) -> list[tuple[float, int]]:
        """返回 [(score, doc_idx)] 降序。"""
        scored = [(self.score(query, i), i) for i in range(self.n)]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        if top_k:
            scored = scored[:top_k]
        return scored


class LocalHashVectorizer:
    """零依赖本地向量：字符 n-gram 哈希（hashing trick）。

    捕获词法变体泛化（如"数据库"/"数据库管理系统"共享 n-gram），
    但非真语义（同义词如"数据库"/"PostgreSQL"无法匹配）。
    网络不可用时的兜底后端。"""

    DIM = 2048
    NGRAMS = (2, 3, 4)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vecs = []
        for text in texts:
            vec = [0.0] * self.DIM
            chars = re.sub(r"\s+", "", text.lower())
            for n in self.NGRAMS:
                for i in range(len(chars) - n + 1):
                    gram = chars[i:i + n]
                    digest = int(hashlib.md5(gram.encode("utf-8")).hexdigest(), 16)
                    idx = digest % self.DIM
                    sign = 1.0 if (digest >> 8) % 2 == 0 else -1.0
                    vec[idx] += sign * (1.0 / n)
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0:
                vec = [v / norm for v in vec]
            vecs.append(vec)
        return vecs


class JinaVectorizer:
    """Jina Embeddings v3 API（1024 维，国际网络）。"""

    URL = "https://api.jina.ai/v1/embeddings"
    MODEL = "jina-embeddings-v3"
    BATCH = 32

    def __init__(self, api_key: str, timeout: int = 30):
        self.key = api_key
        self.timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._embed_batch(texts, "retrieval.passage")

    def embed_query(self, text: str) -> list[float]:
        return self._embed_batch([text], "retrieval.query")[0]

    def _embed_batch(self, texts: list[str], task: str) -> list[list[float]]:
        vecs = []
        for i in range(0, len(texts), self.BATCH):
            chunk = texts[i:i + self.BATCH]
            body = json.dumps({
                "model": self.MODEL, "input": chunk,
                "task": task, "dimensions": 1024,
            }).encode("utf-8")
            req = urllib.request.Request(
                self.URL, data=body,
                headers={"Authorization": f"Bearer {self.key}",
                         "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                raise RuntimeError(f"Jina API HTTP {exc.code}: "
                                   f"{exc.read().decode('utf-8', 'ignore')[:200]}") from exc
            except OSError as exc:
                raise RuntimeError(f"Jina API 网络错误: {exc}") from exc
            vecs.extend(d["embedding"] for d in sorted(data["data"], key=lambda x: x["index"]))
        return vecs


class SiliconFlowVectorizer:
    """硅基流动 BGE-M3（国内网络，OpenAI 兼容格式）。"""

    URL = "https://api.siliconflow.cn/v1/embeddings"
    MODEL = "BAAI/bge-m3"
    BATCH = 32
    QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

    def __init__(self, api_key: str, timeout: int = 30):
        self.key = api_key
        self.timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._embed_batch(texts, prefix="")

    def embed_query(self, text: str) -> list[float]:
        return self._embed_batch([text], prefix=self.QUERY_PREFIX)[0]

    def _embed_batch(self, texts: list[str], prefix: str) -> list[list[float]]:
        vecs = []
        for i in range(0, len(texts), self.BATCH):
            chunk = [prefix + t for t in texts[i:i + self.BATCH]]
            body = json.dumps({"model": self.MODEL, "input": chunk}).encode("utf-8")
            req = urllib.request.Request(
                self.URL, data=body,
                headers={"Authorization": f"Bearer {self.key}",
                         "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                raise RuntimeError(f"硅基流动 API HTTP {exc.code}: "
                                   f"{exc.read().decode('utf-8', 'ignore')[:200]}") from exc
            except OSError as exc:
                raise RuntimeError(f"硅基流动 API 网络错误: {exc}") from exc
            vecs.extend(d["embedding"] for d in sorted(data["data"], key=lambda x: x["index"]))
        return vecs


class VectorStore:
    """向量缓存 + 后端选择。向量存 data/vectors.json（memory_id -> 向量）。

    熔断降级：远端后端（jina/siliconflow）调用失败后自动降级本地哈希向量，
    并把失败状态持久化到 .vector_backend_state.json，避免每轮重复重试。
    恢复远端：删除状态文件，或显式设 HERMES_VECTOR_BACKEND=jina/siliconflow。
    """

    STATE_FILE = ".vector_backend_state.json"

    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / "vectors.json"
        self._encrypt, self._cipher = get_encryption(self.root)
        self._cached_backend: str | None = None
        self.vectors: dict[str, list[float]] = self._load()
        self.backend = None
        self.backend_name = "none"
        self.error = None
        self.state: dict = self._load_state()
        self._init_backend()

    def _load(self) -> dict:
        # 新格式 {"backend": "...", "vectors": {...}}；旧格式为裸 {id: vec}
        if self.path.exists():
            try:
                raw = self.path.read_text(encoding="utf-8")
                data = json.loads(maybe_decrypt(raw, self._cipher))
                if isinstance(data, dict):
                    if "vectors" in data and isinstance(data["vectors"], dict):
                        self._cached_backend = data.get("backend", "unknown")
                        return data["vectors"]
                    self._cached_backend = "unknown"  # 旧格式，强制重建
                    return data
            except (json.JSONDecodeError, OSError):
                pass
        self._cached_backend = None
        return {}

    def _load_state(self) -> dict:
        state_path = self.root / self.STATE_FILE
        if state_path.exists():
            try:
                data = json.loads(state_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save_state(self) -> None:
        (self.root / self.STATE_FILE).write_text(
            json.dumps(self.state, ensure_ascii=False), encoding="utf-8")

    def _get_key(self, env: dict, name: str) -> str | None:
        return os.environ.get(name) or env.get(name)

    def _init_backend(self) -> None:
        mode = os.environ.get("HERMES_VECTOR_BACKEND", "auto").lower()
        env = load_env_file(self.root)
        jina_key = self._get_key(env, "JINA_API_KEY")
        sf_key = self._get_key(env, "SILICONFLOW_API_KEY")

        if mode == "jina":
            if not jina_key:
                self.error = "指定 jina 后端但缺少 JINA_API_KEY"
                return
            self.backend, self.backend_name = JinaVectorizer(jina_key, timeout=10), "jina"
        elif mode == "siliconflow":
            if not sf_key:
                self.error = "指定 siliconflow 后端但缺少 SILICONFLOW_API_KEY"
                return
            self.backend, self.backend_name = SiliconFlowVectorizer(sf_key, timeout=10), "siliconflow"
        elif mode == "local":
            self.backend, self.backend_name = LocalHashVectorizer(), "local"
        else:  # auto —— 尊重熔断状态，避免反复重试不可达的远端
            failed = self.state.get("failed_backend")
            if failed == "jina":
                jina_key = None
            elif failed == "siliconflow":
                sf_key = None
            if jina_key:
                self.backend, self.backend_name = JinaVectorizer(jina_key, timeout=10), "jina"
            elif sf_key:
                self.backend, self.backend_name = SiliconFlowVectorizer(sf_key, timeout=10), "siliconflow"
            else:
                self.backend, self.backend_name = LocalHashVectorizer(), "local"

    def _mark_failed(self, backend_name: str) -> None:
        """远端调用失败 → 持久化熔断 + 立即降级本地。"""
        self.state = {
            "failed_backend": backend_name,
            "failed_at": now_iso(),
            "fallback": "local",
            "error": self.error,
        }
        self._save_state()
        self.backend, self.backend_name = LocalHashVectorizer(), "local"

    def ready(self) -> bool:
        return self.backend is not None

    def ensure(self, entries: list[dict]) -> None:
        """增量补齐缺失向量（只对新记忆生成，避免重复 API 调用）。
        后端切换（如 local→siliconflow）时自动清空缓存重建——不同后端
        的向量维度与语义空间不兼容，混用会破坏检索。"""
        if not self.ready():
            return
        if self._cached_backend != self.backend_name:
            self.vectors = {}
            self._cached_backend = self.backend_name
        missing = [e for e in entries if e["id"] not in self.vectors]
        if not missing:
            return
        try:
            vecs = self.backend.embed([e["content"] for e in missing])
        except RuntimeError as exc:
            self.error = str(exc)
            if self.backend_name != "local":
                self._mark_failed(self.backend_name)  # 降级为 local
            else:
                return
            missing = [e for e in entries if e["id"] not in self.vectors]
            if not missing:
                return
            vecs = self.backend.embed([e["content"] for e in missing])  # local 不会失败
        for entry, vec in zip(missing, vecs):
            self.vectors[entry["id"]] = vec
        self._save()

    def query(self, text: str, top_k: int) -> list[tuple[str, float]]:
        """返回 (memory_id, cosine) 排序列表。远端失败自动降级重试。"""
        if not self.ready() or not self.vectors:
            return []
        try:
            qv = (self.backend.embed_query(text)
                  if hasattr(self.backend, "embed_query") else self.backend.embed([text])[0])
        except RuntimeError as exc:
            self.error = str(exc)
            if self.backend_name != "local":
                self._mark_failed(self.backend_name)
            else:
                return []
            try:
                qv = (self.backend.embed_query(text)
                      if hasattr(self.backend, "embed_query") else self.backend.embed([text])[0])
            except RuntimeError:
                return []
        scored = [(mid, cosine_similarity(qv, vec)) for mid, vec in self.vectors.items()]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]

    def _save(self) -> None:
        payload = {"backend": self.backend_name, "vectors": self.vectors}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(maybe_encrypt(json.dumps(payload), self._cipher), encoding="utf-8")
        os.replace(tmp, self.path)

    def status(self) -> dict:
        return {
            "backend": self.backend_name,
            "ready": self.ready(),
            "vector_count": len(self.vectors),
            "error": self.error,
            "cache_path": str(self.path),
        }


# =====================================================================
# 自动沉淀层（digest）
#  - RuleDigester:  零依赖规则式提取（关键词模式，无 LLM 也可用）
#  - LLMDigester:   LLM 摘要（OpenAI 兼容端点：DeepSeek/硅基流动/通义）
# 后端选择：.env 配置 DEEPSEEK_API_KEY（或 DIGEST_LLM_* 自定义端点）
#           → 有 key 用 LLM，无 key 自动回退规则式
# =====================================================================


class RuleDigester:
    """规则式事实提取：从文本中抽取决策/偏好/配置/项目/事件要点。

    零依赖兜底方案；效果弱于 LLM 摘要，但完全免费且无网络依赖。
    """

    RULES = [
        # (正则, category, 重要性, 展示标签)
        (r"(?:决定|确定|选择|采用|采纳)\s*(?:了)?\s*([^。；;！!？?]{4,60})", "decision", 8, "决定"),
        (r"(?:偏好|喜欢|习惯|常用|倾向)\s*(?:于|用|使用)?\s*([^。；;！!？?]{2,40})", "preference", 7, "偏好"),
        (r"(?:配置|端口|路径|地址|超时|安装)\s*(?:为|是|在|于|了)?\s*([^。；;！!？?]{2,40})", "config", 6, "配置"),
        (r"(?:正在|准备|计划|开始)\s*(?:开发|做|推进|评估|研究|落地)\s*([^。；;！!？?]{2,50})", "project", 7, "项目"),
        (r"(?:完成|交付|上线|发布|通过)\s*(?:了)?\s*([^。；;！!？?]{2,50})", "event", 5, "事件"),
    ]

    def digest(self, text: str) -> list[dict]:
        facts: list[dict] = []
        seen = set()
        for pattern, category, importance, label in self.RULES:
            for match in re.finditer(pattern, text):
                value = match.group(1).strip().strip("，,。")
                if len(value) < 2:
                    continue
                key = value[:20]
                if key in seen:
                    continue
                seen.add(key)
                facts.append({
                    "content": f"{label}：{value}",
                    "category": category,
                    "importance": importance,
                })
        return facts


class LLMDigester:
    """LLM 摘要（OpenAI 兼容 chat completions）。

    默认 DeepSeek（国内直连）；可用环境变量覆盖端点/模型：
      DEEPSEEK_API_KEY / DIGEST_LLM_BASE_URL / DIGEST_LLM_MODEL
    """

    DEFAULT_BASE_URL = "https://api.deepseek.com"
    DEFAULT_MODEL = "deepseek-chat"
    SYSTEM_PROMPT = (
        "你是记忆沉淀助手。从用户提供的对话文本中，提取值得长期记住的稳定事实"
        "（用户偏好、技术/业务决策、系统配置、项目进展、重要事件）。\n"
        "要求：\n"
        "1. 忽略寒暄、提问、情绪化表达和一次性内容\n"
        "2. 每条事实一句话，简洁准确，保留关键数值（端口、路径、版本等）\n"
        "3. 敏感信息（密码/token/密钥）不要输出原文，写'（敏感信息，已脱敏）'\n"
        "4. 只输出 JSON 数组，每项格式："
        '{"content": "事实", "category": "preference|decision|config|project|event", '
        '"importance": 1-10 的整数}\n'
        "5. 无值得记忆的内容时输出 []"
    )

    def __init__(self, api_key: str, base_url: str | None = None,
                 model: str | None = None, timeout: int = 60):
        self.key = api_key
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.model = model or self.DEFAULT_MODEL
        self.timeout = timeout
        self.last_usage: dict = {}

    def digest(self, text: str) -> list[dict]:
        if not text.strip():
            return []
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": text[:8000]},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body,
            headers={"Authorization": f"Bearer {self.key}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"LLM 摘要 API HTTP {exc.code}: "
                               f"{exc.read().decode('utf-8', 'ignore')[:200]}") from exc
        except OSError as exc:
            raise RuntimeError(f"LLM 摘要 API 网络错误: {exc}") from exc
        content = data["choices"][0]["message"]["content"]
        self.last_usage = data.get("usage", {})
        return self._parse_facts(content)

    @staticmethod
    def _parse_facts(content: str) -> list[dict]:
        # 兼容 json_object 输出（可能是 {"facts": [...]} 或裸数组）
        text = content.strip()
        for pattern in (r"\{[^{}]*\"facts\"\s*:\s*(\[.*\])\s*\}",
                        r"(\[\s*\{.*\}\s*\])"):
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    if isinstance(data, list):
                        return [f for f in data if isinstance(f, dict) and f.get("content")]
                except json.JSONDecodeError:
                    continue
        # 逐行兜底：提取 "content": "..." 
        facts = []
        for m in re.finditer(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', text):
            facts.append({"content": m.group(1), "category": "event", "importance": 5})
        return facts


class SiliconFlowReranker:
    """硅基流动 BGE-reranker-v2-m3（精排层）。

    对 BM25 + 向量两路召回的候选做相关性精排，显著提升 top-k 精度。
    失败自动降级（进程内熔断），不影响基础检索。
    """

    URL = "https://api.siliconflow.cn/v1/rerank"
    MODEL = "BAAI/bge-reranker-v2-m3"

    def __init__(self, api_key: str, timeout: int = 20):
        self.key = api_key
        self.timeout = timeout

    def rerank(self, query: str, documents: list[str], top_k: int = 5) -> list[tuple[int, float]]:
        """返回 [(doc_index, relevance_score)] 按相关性降序。"""
        if not documents:
            return []
        body = json.dumps({
            "model": self.MODEL,
            "query": query,
            "documents": documents[:64],
            "top_n": top_k,
        }).encode("utf-8")
        req = urllib.request.Request(
            self.URL, data=body,
            headers={"Authorization": f"Bearer {self.key}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Rerank API HTTP {exc.code}: "
                               f"{exc.read().decode('utf-8', 'ignore')[:200]}") from exc
        except OSError as exc:
            raise RuntimeError(f"Rerank API 网络错误: {exc}") from exc
        results = sorted(data.get("results", []),
                         key=lambda r: r["relevance_score"], reverse=True)
        return [(r["index"], r["relevance_score"]) for r in results]


class DigestEngine:
    """digest 后端选择：有 LLM key 用 LLM，否则规则式。"""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.llm = None
        self.mode = "rule"
        env = load_env_file(self.root)
        api_key = os.environ.get("DEEPSEEK_API_KEY") or env.get("DEEPSEEK_API_KEY")
        if api_key:
            try:
                self.llm = LLMDigester(
                    api_key,
                    os.environ.get("DIGEST_LLM_BASE_URL") or env.get("DIGEST_LLM_BASE_URL"),
                    os.environ.get("DIGEST_LLM_MODEL") or env.get("DIGEST_LLM_MODEL"),
                )
                self.mode = "llm"
            except Exception:
                self.llm = None

    def digest(self, text: str) -> list[dict]:
        if self.llm:
            try:
                return self.llm.digest(text)
            except RuntimeError:
                pass  # 失败回退规则式
        return RuleDigester().digest(text)


# =====================================================================
# 记忆图谱层（实体 → 记忆关联）
# 规则式实体抽取（专有名词/版本号），存 data/graph.json
# =====================================================================

# 常见中性词（非技术实体），过滤误抽
ENTITY_STOPWORDS = {
    "The", "This", "That", "These", "Those", "We", "You", "They", "He",
    "She", "It", "I", "Me", "My", "Our", "Your", "Their", "In", "On",
    "At", "For", "And", "But", "Or", "Not", "No", "Yes", "A", "An",
    "To", "Of", "With", "From", "By", "Is", "Are", "Was", "Were", "Be",
}


def extract_entities(text: str) -> dict[str, str]:
    """规则式实体抽取：返回 {实体名: 类型}。类型: tech / version。"""
    entities: dict[str, str] = {}
    for m in re.finditer(r"\b[A-Z][A-Za-z0-9_\-]{1,}\b", text):
        word = m.group(0)
        if word in ENTITY_STOPWORDS:
            continue
        if re.match(r"^[A-Z](?:[0-9]|_)", word):
            continue
        entities.setdefault(word, "tech")
    for m in re.finditer(r"\b\d{1,2}\.\d{1,2}(?:\.\d+)?\b", text):
        entities.setdefault(m.group(0), "version")
    for m in re.finditer(r"\b[Vv]\d+(?:\.\d+)+\b", text):
        entities.setdefault(m.group(0), "version")
    return entities


class GraphStore:
    """记忆图谱：实体 ↔ 记忆 多对多关联。"""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / "graph.json"
        self._encrypt, self._cipher = get_encryption(self.root)
        self.data: dict = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                raw = self.path.read_text(encoding="utf-8")
                data = json.loads(maybe_decrypt(raw, self._cipher))
                if isinstance(data, dict) and "entities" in data:
                    return data
            except (json.JSONDecodeError, OSError):
                pass
        return {"entities": {}}

    def _save(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(maybe_encrypt(
            json.dumps(self.data, ensure_ascii=False, indent=2), self._cipher),
            encoding="utf-8")
        os.replace(tmp, self.path)

    def _add(self, entry: dict) -> None:
        for name, etype in extract_entities(entry["content"]).items():
            node = self.data["entities"].setdefault(name, {"type": etype, "memory_ids": []})
            if entry["id"] not in node["memory_ids"]:
                node["memory_ids"].append(entry["id"])

    def update(self, entry: dict) -> None:
        self._add(entry)
        self._save()

    def build(self, entries: list[dict]) -> None:
        self.data = {"entities": {}}
        for entry in entries:
            self._add(entry)
        self._save()

    def remove(self, memory_id: str) -> None:
        for node in self.data["entities"].values():
            if memory_id in node["memory_ids"]:
                node["memory_ids"].remove(memory_id)
        self.data["entities"] = {k: v for k, v in self.data["entities"].items()
                                 if v["memory_ids"]}
        self._save()

    def list_entities(self, top_k: int = 15) -> list[tuple[str, int, str]]:
        ents = [(name, len(node["memory_ids"]), node["type"])
                for name, node in self.data["entities"].items()]
        ents.sort(key=lambda x: -x[1])
        return ents[:top_k]

    def memories_for(self, entity: str, index: list[dict]) -> list[dict]:
        node = self.data["entities"].get(entity)
        if not node:
            return []
        return [e for e in index if e["id"] in node["memory_ids"]]


class HermesLite:
    """轻量五层记忆：入口层(remember/verify) + 房间存储 + 加权检索 + 淘汰 + 统计。"""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root else Path(
            os.environ.get("HERMES_LITE_ROOT") or DEFAULT_ROOT)
        self.rooms_dir = self.root / "rooms"
        self.store_dir = self.root / "store"
        self.backup_dir = self.root / "backups"
        self.index_path = self.root / "index.json"
        for d in (self.rooms_dir, self.store_dir, self.backup_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._encrypt, self._cipher = get_encryption(self.root)
        self.config = self._load_config()
        self.index = self._load_index()
        self.vectors = VectorStore(self.root)
        self._bm25: BM25Index | None = None
        self._reranker: SiliconFlowReranker | None = None
        self._rerank_ok = True
        self.graph = GraphStore(self.root)
        self._init_reranker()
        self._ensure_room_readmes()

    def _init_reranker(self) -> None:
        """初始化 Rerank 精排器（默认开启，HERMES_RERANK=off 关闭）。"""
        if os.environ.get("HERMES_RERANK", "on").lower() == "off":
            return
        env = load_env_file(self.root)
        api_key = os.environ.get("SILICONFLOW_API_KEY") or env.get("SILICONFLOW_API_KEY")
        if api_key:
            self._reranker = SiliconFlowReranker(api_key)

    # ---------- 基础设施 ----------

    def _load_config(self) -> dict:
        config = DEFAULT_CONFIG
        path = self.root / CONFIG_NAME
        if yaml is not None and path.exists():
            try:
                loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                config = deep_merge(config, loaded)
            except Exception as exc:  # 配置损坏不应阻断系统
                print(f"⚠️ 配置加载失败（{exc}），使用默认配置", file=sys.stderr)
        return config

    def _load_index(self) -> list:
        if self.index_path.exists():
            try:
                raw = self.index_path.read_text(encoding="utf-8")
                data = json.loads(maybe_decrypt(raw, self._cipher))
                if isinstance(data, list):
                    return data
            except (json.JSONDecodeError, OSError):
                pass
        return []

    def _save_index(self) -> None:
        self._atomic_write(self.index_path, json.dumps(self.index, ensure_ascii=False, indent=2))

    def _atomic_write(self, path: Path, content: str) -> None:
        """原子写入：先写临时文件再 rename（防写一半崩溃损坏数据）。
        开启加密时（HERMES_ENCRYPT=on）内容以 Fernet AES 密文落盘。"""
        if self._encrypt:
            content = maybe_encrypt(content, self._cipher)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
        self._auto_backup(path)

    def _auto_backup(self, path: Path, keep: int = 7) -> None:
        """每日首次写入前自动备份（保留最近 keep 份），写入后调用。"""
        if not path.exists():
            return
        backup = self.backup_dir / f"auto_{path.name}.{datetime.now().strftime('%Y%m%d')}.bak"
        if backup.exists():
            return
        shutil.copy2(path, backup)
        backups = sorted(self.backup_dir.glob(f"auto_{path.name}.*.bak"))
        for old in backups[:-keep]:
            old.unlink()

    def _room_info(self, room_id: str) -> dict:
        return self.config["rooms"].get(room_id, {
            "name": room_id, "icon": "📌", "retention_days": 90})

    def _ensure_room_readmes(self) -> None:
        for room_id, info in self.config["rooms"].items():
            readme = self.rooms_dir / f"{room_id}.md"
            if not readme.exists():
                readme.write_text(
                    f"# {info.get('icon', '')} {info['name']}房间\n\n"
                    f"**描述**: {info.get('description', '')}\n"
                    f"**保留期限**: {info.get('retention_days', 90)} 天\n",
                    encoding="utf-8")

    def _find(self, memory_id: str) -> dict | None:
        for entry in self.index:
            if entry["id"] == memory_id:
                return entry
        return None

    # ---------- BM25 缓存 ----------

    def _invalidate_bm25(self) -> None:
        """记忆变更后失效 BM25 索引（下次检索重建）。"""
        self._bm25 = None

    def _ensure_bm25(self) -> BM25Index:
        if self._bm25 is None or len(self._bm25.docs) != len(self.index):
            self._bm25 = BM25Index([e["content"] for e in self.index])
        return self._bm25

    # ---------- L0 入口层：No Execution, No Memory ----------

    def remember(self, text: str, category: str = "event", importance: int = 5,
                 verified: bool = False, source: str = None,
                 created_at: str | None = None) -> dict:
        """写入记忆。核心原则：默认未验证（execution_verified=False）。
        与已有记忆高度相似时自动合并更新（去重），避免记忆库膨胀。"""
        text = text.strip()
        if not text:
            raise ValueError("记忆内容不能为空")
        importance = max(1, min(int(importance), 10))

        redacted_text, redacted_types = self._redact(text)

        # 冲突检测：新记忆与旧记忆矛盾时提示（不阻止写入）
        conflicts = self._find_conflicts(redacted_text)

        # 去重合并：相似度 ≥ 阈值时更新旧条目而非新增
        duplicate = self._find_duplicate(redacted_text)
        if duplicate:
            duplicate["content"] = redacted_text
            duplicate["importance"] = max(duplicate["importance"], importance)
            duplicate["category"] = category
            duplicate["room"] = self.config["category_mapping"].get(category, "events")
            if verified:
                duplicate["execution_verified"] = True
            if source:
                duplicate["source"] = source
            duplicate["redacted"] = sorted(set(duplicate.get("redacted", [])) | redacted_types)
            self._write_store_file(duplicate)
            self._save_index()
            self._invalidate_bm25()
            self.graph.remove(duplicate["id"])
            self.graph.update(duplicate)
            result = {"id": duplicate["id"], "room": duplicate["room"], "merged": True}
            if redacted_types:
                result["redacted"] = sorted(redacted_types)
            if conflicts:
                result["conflicts"] = conflicts
            return result

        room = self.config["category_mapping"].get(category, "events")
        memory_id = f"mem_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"

        entry = {
            "id": memory_id,
            "content": redacted_text,
            "category": category,
            "room": room,
            "importance": importance,
            "execution_verified": bool(verified),
            "access_count": 0,
            "last_accessed": None,
            "source": source,
            "created_at": created_at or now_iso(),
            "redacted": sorted(redacted_types),
        }
        self.index.append(entry)
        self._write_store_file(entry)
        self._save_index()
        self._invalidate_bm25()
        self.graph.update(entry)

        result = {"id": memory_id, "room": room}
        if redacted_types:
            result["redacted"] = sorted(redacted_types)
        if conflicts:
            result["conflicts"] = conflicts
        return result

    def _find_duplicate(self, text: str, threshold: float = 0.85) -> dict | None:
        """查找与文本高度相似的已有记忆（字符相似度 SequenceMatcher）。"""
        best, best_ratio = None, 0.0
        for entry in self.index:
            existing = entry["content"]
            if len(existing) < 5 or len(text) < 5:
                continue
            ratio = difflib.SequenceMatcher(None, existing, text).ratio()
            if ratio > best_ratio:
                best, best_ratio = entry, ratio
        return best if best_ratio >= threshold else None

    def _find_conflicts(self, text: str) -> list[dict]:
        """冲突检测：新记忆与旧记忆对同一实体持相反断言时提示。

        规则式：提取正断言（决定/采用/使用 X）与负断言（放弃/不用 X），
        若新旧记忆对同一实体断言相反则视为潜在矛盾。
        """
        pos_pattern = r"(?:决定|选择|采用|使用|选用|用)\s*(?:了|的)?\s*([A-Za-z0-9_\-.]+)"
        neg_pattern = r"(?:放弃|不用|弃用|反对|拒绝|移除|取消|停止)\s*(?:了|的)?\s*([A-Za-z0-9_\-.]+)"
        new_pos = set(re.findall(pos_pattern, text))
        new_neg = set(re.findall(neg_pattern, text))
        conflicts = []
        for entry in self.index:
            e_pos = set(re.findall(pos_pattern, entry["content"]))
            e_neg = set(re.findall(neg_pattern, entry["content"]))
            for entity in (new_neg & e_pos):
                conflicts.append({"memory_id": entry["id"], "entity": entity,
                                  "type": "新记忆否定，旧记忆肯定", "content": entry["content"]})
            for entity in (new_pos & e_neg):
                conflicts.append({"memory_id": entry["id"], "entity": entity,
                                  "type": "新记忆肯定，旧记忆否定", "content": entry["content"]})
        return conflicts

    def verify(self, memory_id: str) -> dict:
        """执行验证：标记记忆为已验证（对应 L0 的 execution_verified 参数）。"""
        entry = self._find(memory_id)
        if not entry:
            raise KeyError(f"记忆不存在: {memory_id}")
        entry["execution_verified"] = True
        self._write_store_file(entry)
        self._save_index()
        return {"id": memory_id, "execution_verified": True}

    def _redact(self, text: str) -> tuple[str, set]:
        """敏感信息脱敏：原文不落盘。返回 (脱敏文本, 脱敏类型集合)。"""
        redacted_types = set()
        patterns = self.config["security"]["redact_patterns"]
        for pattern in patterns:
            compiled = re.compile(pattern, re.IGNORECASE)
            if not compiled.search(text):
                continue
            # 标记类型：从模式里的关键词推断
            label = "secret"
            for keyword, tag in (("密码", "password"), ("口令", "password"), ("passwd", "password"),
                                 ("password", "password"), ("api", "api_key"), ("key", "api_key"),
                                 ("密钥", "api_key"), ("token", "token"), ("secret", "token"),
                                 ("授权码", "token"), ("sk-", "api_key"), ("Bearer", "token")):
                if keyword.lower() in pattern.lower():
                    label = tag
                    break
            redacted_types.add(label)
            text = compiled.sub(lambda m: self._redact_replacement(m, label), text)
        return text, redacted_types

    @staticmethod
    def _redact_replacement(match: re.Match, label: str) -> str:
        groups = match.groups()
        if len(groups) >= 2 and groups[0]:
            # 形如 "密码：xxx"（前缀组 + 值组）——保留前缀，替换值
            return f"{groups[0]}[已脱敏:{label}]"
        # 独立 token（sk-xxx / Bearer xxx，单捕获组）——整体替换，严禁明文残留
        return f"[已脱敏:{label}]"

    # ---------- 存储层（Obsidian 兼容 Markdown） ----------

    def _write_store_file(self, entry: dict) -> None:
        header = "---\n"
        for key in ("id", "category", "room", "importance",
                    "execution_verified", "access_count", "last_accessed",
                    "source", "created_at"):
            value = entry.get(key)
            if value is not None:
                header += f"{key}: {value}\n"
        if entry.get("redacted"):
            header += f"redacted: {','.join(entry['redacted'])}\n"
        header += "---\n\n"
        (self.store_dir / f"{entry['id']}.md").write_text(
            header + entry["content"] + "\n", encoding="utf-8")

    # ---------- 检索层（真实打分，非伪造指标） ----------

    def _keyword_rank(self, query: str, room: str | None = None,
                      top_k: int | None = None) -> list[tuple[float, dict]]:
        """BM25 关键词打分排序（词法层）。返回 [(score, entry)] 降序。"""
        top_k = top_k or self.config["retrieval"]["default_top_k"]
        if room and room not in self.config["rooms"]:
            raise KeyError(f"未知房间: {room}（可用: {', '.join(self.config['rooms'])})")

        bm25 = self._ensure_bm25()
        scored = []
        hot_threshold = self.config["retrieval"].get("hot_threshold", 5)
        hot_boost = self.config["retrieval"].get("hot_boost", 1.1)
        for score, idx in bm25.search(query):
            if score <= 0:
                break  # 已按分降序，后续全为 0
            entry = self.index[idx]
            if room and entry["room"] != room:
                continue
            # 冷热分层：高频访问记忆（hot）权重加成
            if entry.get("access_count", 0) >= hot_threshold:
                score *= hot_boost
            scored.append((score, entry))
        return scored[:top_k]

    def recall(self, query: str, room: str | None = None, top_k: int | None = None) -> list[dict]:
        """混合检索：关键词打分 + 向量余弦，RRF 融合排序。

        向量层不可用/无命中时自动回退纯关键词。向量召回引入新候选
        时要求余弦 ≥ 阈值（local 0.30 / 远程 0.35），过滤无关噪声。
        """
        top_k = top_k or self.config["retrieval"]["default_top_k"]
        min_score = self.config["retrieval"]["min_score"]

        kw_ranked = self._keyword_rank(query, room=room, top_k=None)

        # 向量召回（增量补齐向量 + 房间过滤 + 相似度阈值）
        self.vectors.ensure(self.index)
        vector_hits: list[tuple[str, float]] = []
        if self.vectors.ready():
            threshold = 0.30 if self.vectors.backend_name == "local" else 0.35
            all_hits = self.vectors.query(query, top_k=len(self.index))
            if room:
                all_hits = [(mid, cos) for mid, cos in all_hits
                            if (entry := self._find(mid)) and entry["room"] == room]
            vector_hits = [(mid, cos) for mid, cos in all_hits if cos >= threshold]

        # 融合排序
        if vector_hits:
            kw_ids = [e["id"] for _, e in kw_ranked]
            vec_ids = [mid for mid, _ in vector_hits]
            fused = rrf_merge([kw_ids, vec_ids])
            final_ids = [doc_id for doc_id, _ in fused]
        else:
            final_ids = [e["id"] for _, e in kw_ranked]

        # Rerank 精排（可选层：BM25+向量召回候选 → rerank 相关性精排 → top-k）
        rerank_scores: dict[str, float] = {}
        if self._reranker and self._rerank_ok and len(final_ids) > 1:
            candidates = [self._find(doc_id) for doc_id in final_ids[:20]]
            candidates = [e for e in candidates if e]
            try:
                reranked = self._reranker.rerank(
                    query, [e["content"] for e in candidates], top_k=top_k)
                final_ids = [candidates[i]["id"] for i, _ in reranked]
                rerank_scores = {candidates[i]["id"]: round(score, 3)
                                 for i, score in reranked}
            except RuntimeError:
                self._rerank_ok = False  # 进程内熔断，本次后续跳过

        results = []
        for doc_id in final_ids[:top_k]:
            entry = self._find(doc_id)
            if entry is None:
                continue
            kw_score = next((s for s, e in kw_ranked if e["id"] == doc_id), 0.0)
            vec_score = next((c for mid, c in vector_hits if mid == doc_id), 0.0)
            display_score = kw_score if kw_score > 0 else round(vec_score * 3, 2)
            if kw_score == 0 and vec_score == 0:
                continue
            if kw_score == 0 and vec_score < min_score / 3:
                continue
            entry["access_count"] += 1
            entry["last_accessed"] = now_iso()
            # 重要性自适应：每 10 次访问 importance+1（上限 10）
            if entry["access_count"] % 10 == 0 and entry["importance"] < 10:
                entry["importance"] += 1
            results.append({
                "id": entry["id"], "room": entry["room"], "category": entry["category"],
                "importance": entry["importance"], "verified": entry["execution_verified"],
                "created_at": entry["created_at"], "score": display_score,
                "kw_score": round(kw_score, 2), "vec_score": round(vec_score, 3),
                "rerank_score": rerank_scores.get(doc_id),
                "content": entry["content"],
            })
        if results:
            self._save_index()
        return results

    @staticmethod
    def _extract_ascii_tokens(text: str) -> list[str]:
        """提取 ASCII/数字词（端口、名称、API 等）。"""
        return [t for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9_\-\.]{1,}", text) if len(t) >= 2]

    @staticmethod
    def _char_ngrams(text: str, n: int = 2) -> set[str]:
        """中文 n-gram 字符块集合（对中文文本做近似词元化）。"""
        chars = re.sub(r"\s+", "", text)
        return {chars[i:i + n] for i in range(len(chars) - n + 1)} if len(chars) >= n else set()

    def _score(self, entry: dict, ascii_tokens: list[str], ngrams: set[str]) -> float:
        content = entry["content"]
        score = 0.0
        cfg = self.config["retrieval"]

        for token in ascii_tokens:
            if token.lower() in content.lower():
                score += 2.0 * min(len(token), 8) / 4.0

        content_ngrams = self._char_ngrams(content, n=2)
        overlap = ngrams & content_ngrams
        score += 0.3 * len(overlap)

        if score == 0:
            return 0.0

        score += entry["importance"] * cfg["weight_importance"]
        score += math.log1p(entry["access_count"]) * cfg["weight_frequency"]
        if entry["execution_verified"]:
            score += cfg["weight_verified"]

        age_days = days_between(entry["created_at"], now_iso())
        decay_days = cfg["time_decay_days"]
        if age_days > decay_days:
            score *= (decay_days / age_days) ** 0.3
        if entry["execution_verified"]:
            score *= cfg["boost_verified"]
        return score

    # ---------- 淘汰层（真实实现） ----------

    def _retention_days(self, entry: dict) -> int:
        """保留天数：关键记忆永久 > 房间策略 > 未验证短留 > 默认。"""
        pruning = self.config["pruning"]
        if entry["importance"] >= pruning["critical_importance"]:
            return math.inf
        room = self._room_info(entry["room"])
        if not entry["execution_verified"]:
            return pruning["unverified_retention_days"]
        return room["retention_days"]

    def find_expired(self, room: str | None = None) -> list[dict]:
        """找出过期记忆（真实查找，非空壳）。"""
        pruning = self.config["pruning"]
        now = now_iso()
        expired = []
        for entry in self.index:
            if room and entry["room"] != room:
                continue
            retention = self._retention_days(entry)
            if math.isinf(retention):
                continue
            if days_between(entry["created_at"], now) >= retention:
                expired.append(entry)
                continue
            # 低频规则：访问 < 阈值且创建超过低频天数
            if (entry["access_count"] < pruning["low_frequency_threshold"]
                    and days_between(entry["created_at"], now) >= pruning["low_frequency_days"]):
                expired.append(entry)
        return expired

    def prune(self, dry_run: bool = True, room: str | None = None) -> dict:
        """执行淘汰：归档到 backups/ 后删除。dry_run 只统计不删除。"""
        expired = self.find_expired(room=room)
        result = {
            "dry_run": dry_run,
            "expired_count": len(expired),
            "expired_ids": [e["id"] for e in expired],
            "archived": 0,
            "deleted": 0,
        }
        if not expired or dry_run:
            return result

        archive_path = self.backup_dir / f"prune_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        archive_path.write_text(json.dumps({
            "archived_at": now_iso(),
            "memories": expired,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        expired_ids = {e["id"] for e in expired}
        self.index = [e for e in self.index if e["id"] not in expired_ids]
        for memory_id in expired_ids:
            store_file = self.store_dir / f"{memory_id}.md"
            if store_file.exists():
                store_file.unlink()
            self.vectors.vectors.pop(memory_id, None)
        self._save_index()
        if expired_ids:
            self.vectors._save()
        self._invalidate_bm25()
        if expired_ids:
            self.graph.build(self.index)  # 全量重建，简单可靠（记忆量小）
        result["archived"] = len(expired)
        result["deleted"] = len(expired)
        return result

    def forget(self, memory_id: str) -> dict:
        """删除单条记忆。"""
        entry = self._find(memory_id)
        if not entry:
            raise KeyError(f"记忆不存在: {memory_id}")
        self.index = [e for e in self.index if e["id"] != memory_id]
        store_file = self.store_dir / f"{memory_id}.md"
        if store_file.exists():
            store_file.unlink()
        self.vectors.vectors.pop(memory_id, None)
        self.vectors._save()
        self._save_index()
        self._invalidate_bm25()
        self.graph.remove(memory_id)
        return {"id": memory_id, "deleted": True}

    # ---------- 统计层 ----------

    def stats(self) -> dict:
        rooms = {}
        for room_id, info in self.config["rooms"].items():
            rooms[room_id] = {"name": info["name"], "count": 0}
        verified = unverified = 0
        total_importance = 0
        for entry in self.index:
            rooms.setdefault(entry["room"], {"name": entry["room"], "count": 0})
            rooms[entry["room"]]["count"] += 1
            verified += 1 if entry["execution_verified"] else 0
            unverified += 0 if entry["execution_verified"] else 1
            total_importance += entry["importance"]
        store_bytes = sum(f.stat().st_size for f in self.store_dir.glob("*.md"))
        hot_threshold = self.config["retrieval"].get("hot_threshold", 5)
        hot = sum(1 for e in self.index if e.get("access_count", 0) >= hot_threshold)
        cold = sum(1 for e in self.index if e.get("access_count", 0) < 3)
        return {
            "total": len(self.index),
            "rooms": rooms,
            "verified": verified,
            "unverified": unverified,
            "hot": hot,
            "cold": cold,
            "avg_importance": round(total_importance / len(self.index), 2) if self.index else 0.0,
            "store_bytes": store_bytes,
            "index_path": str(self.index_path),
        }

    def list_rooms(self) -> list[dict]:
        stats = self.stats()
        return [{
            "id": rid, "name": info["name"], "icon": info.get("icon", ""),
            "retention_days": info["retention_days"], "count": stats["rooms"].get(rid, {}).get("count", 0),
        } for rid, info in self.config["rooms"].items()]

    # ---------- 自动沉淀层 ----------

    def digest(self, text: str, apply: bool = False, max_facts: int = 10,
               verified: bool = False, source: str = "auto-digest") -> dict:
        """自动沉淀：提取对话要点。apply=False 只预览不写入。

        复用完整记忆链路：脱敏 → 去重合并 → 默认未验证（No Execution, No Memory）。
        """
        engine = DigestEngine(self.root)
        facts = engine.digest(text)[:max_facts]
        result = {"mode": engine.mode, "facts": facts, "applied": []}
        if apply:
            for fact in facts:
                r = self.remember(
                    fact["content"], category=fact.get("category", "event"),
                    importance=fact.get("importance", 5), verified=verified,
                    source=source)
                result["applied"].append(r)
        return result


# ---------- CLI ----------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hermes_lite", description="Agent Memory - 智能体记忆/学习/进化系统")
    parser.add_argument("--root", default=None, help="数据根目录（默认 ~/.hermes-lite 或 $HERMES_LITE_ROOT）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_remember = sub.add_parser("remember", help="写入记忆（默认未验证）")
    p_remember.add_argument("text", help="记忆内容")
    p_remember.add_argument("--category", default="event",
                            choices=["preference", "decision", "config", "project",
                                     "event", "discussion", "idea", "general"])
    p_remember.add_argument("--importance", type=int, default=5, help="重要性 1-10")
    p_remember.add_argument("--verified", action="store_true", help="标记为已验证（执行验证）")
    p_remember.add_argument("--source", default=None, help="来源（如：WeCom对话）")

    p_recall = sub.add_parser("recall", help="检索记忆（关键词 + 向量混合）")
    p_recall.add_argument("query", help="查询内容")
    p_recall.add_argument("--room", default=None, help="房间过滤")
    p_recall.add_argument("--top-k", type=int, default=None, help="返回条数")

    p_vsearch = sub.add_parser("vsearch", help="纯向量检索（显示余弦相似度）")
    p_vsearch.add_argument("query", help="查询内容")
    p_vsearch.add_argument("--top-k", type=int, default=5)

    sub.add_parser("vectors", help="向量后端状态")

    p_graph = sub.add_parser("graph", help="记忆图谱：实体与记忆关联")
    p_graph.add_argument("entity", nargs="?", help="查询某实体的关联记忆")
    p_graph.add_argument("--top", type=int, default=15, help="列出实体数量")
    p_graph.add_argument("--rebuild", action="store_true", help="全量重建图谱")

    p_digest = sub.add_parser("digest", help="自动沉淀：从对话文本提取记忆要点")
    p_digest.add_argument("text", nargs="?", help="文本内容（与 --file 二选一）")
    p_digest.add_argument("--file", default=None, help="从文件读取对话文本")
    p_digest.add_argument("--apply", action="store_true", help="直接写入记忆（默认仅预览）")
    p_digest.add_argument("--max", type=int, default=10, help="最多提取条数")
    p_digest.add_argument("--verified", action="store_true", help="写入时标记已验证")

    p_verify = sub.add_parser("verify", help="执行验证某条记忆")
    p_verify.add_argument("memory_id")

    p_prune = sub.add_parser("prune", help="淘汰过期记忆")
    p_prune.add_argument("--dry-run", action="store_true", help="只统计不删除")
    p_prune.add_argument("--room", default=None)
    p_prune.add_argument("--yes", action="store_true", help="跳过确认")

    p_forget = sub.add_parser("forget", help="删除单条记忆")
    p_forget.add_argument("memory_id")
    p_forget.add_argument("--yes", action="store_true", help="跳过确认")

    sub.add_parser("stats", help="记忆统计")
    sub.add_parser("rooms", help="列出房间")
    return parser


def print_recall(results: list[dict]) -> None:
    if not results:
        print("（无相关记忆）")
        return
    for r in results:
        mark = "✅已验证" if r["verified"] else "⬜未验证"
        scores = f"kw={r.get('kw_score', '-')} vec={r.get('vec_score', '-')}"
        if r.get("rerank_score") is not None:
            scores += f" rerank={r['rerank_score']}"
        print(f"[{r['score']:>5.2f}] {r['id']}  {r['room']}  重要{r['importance']}  {mark}  ({scores})")
        print(f"      {r['content']}")
        print(f"      ⏱ {r['created_at'][:16]}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    mem = HermesLite(root=args.root)

    if args.command == "remember":
        result = mem.remember(args.text, category=args.category,
                              importance=args.importance, verified=args.verified,
                              source=args.source)
        if result.get("merged"):
            line = f"🔁 检测到重复，已合并更新 {result['id']} → 房间: {result['room']}"
        else:
            line = f"✅ 已记忆 {result['id']} → 房间: {result['room']}"
        if result.get("redacted"):
            line += f"（脱敏: {', '.join(result['redacted'])}）"
        print(line)
        if result.get("conflicts"):
            print("⚠️  冲突警告（新记忆与旧记忆矛盾）：")
            for c in result["conflicts"]:
                print(f"   - [{c['entity']}] {c['type']}")
                print(f"     旧记忆 {c['memory_id']}: {c['content']}")

    elif args.command == "recall":
        print_recall(mem.recall(args.query, room=args.room, top_k=args.top_k))

    elif args.command == "vsearch":
        mem.vectors.ensure(mem.index)
        hits = mem.vectors.query(args.query, top_k=args.top_k)
        if not hits:
            print("（向量库为空或后端不可用，运行 recall 一次会自动生成向量）")
        for mid, cos in hits:
            entry = mem._find(mid)
            if entry:
                print(f"[{cos:.3f}] {mid}  {entry['room']}  {entry['content']}")

    elif args.command == "vectors":
        status = mem.vectors.status()
        print(f"🧠 向量后端: {status['backend']} | 就绪: {status['ready']} | 已缓存向量: {status['vector_count']} 条")
        if status["error"]:
            print(f"⚠️  后端错误: {status['error']}")
        if mem.vectors.state.get("failed_backend"):
            state = mem.vectors.state
            print(f"🔌 熔断记录: {state['failed_backend']} 失败于 {state['failed_at'][:16]}，已降级 local")
            print("   恢复远端: 删除 data/.vector_backend_state.json 或设 HERMES_VECTOR_BACKEND=jina")
        print(f"   缓存文件: {status['cache_path']}")
        print("   切换: HERMES_VECTOR_BACKEND=auto|local|jina|siliconflow")
        print("   key 来源: 环境变量 或 data/.env（600 权限）")
        if mem._reranker:
            state = "开启" if mem._rerank_ok else "已熔断（本次进程跳过）"
            print(f"🎯 Rerank 精排: {state}（{mem._reranker.MODEL}，HERMES_RERANK=off 可关）")
        else:
            print("🎯 Rerank 精排: 未启用（需 SILICONFLOW_API_KEY，HERMES_RERANK=on 开启）")

    elif args.command == "graph":
        if args.rebuild:
            mem.graph.build(mem.index)
            print("✅ 记忆图谱已全量重建")
            if not args.entity:
                return 0
        if args.entity:
            mems = mem.graph.memories_for(args.entity, mem.index)
            if not mems:
                print(f"🔗 实体 {args.entity}: 无关联记忆（试试 graph 看已有实体）")
            else:
                print(f"🔗 实体 {args.entity} 关联 {len(mems)} 条记忆:")
                for e in mems:
                    print(f"   - [{e['room']}] {e['content']}")
        else:
            ents = mem.graph.list_entities(top_k=args.top)
            if not ents:
                print("🕸️ 图谱为空（写入记忆后自动构建，或 graph --rebuild）")
            else:
                print(f"🕸️ 记忆图谱（前 {len(ents)} 个实体）:")
                for name, count, etype in ents:
                    print(f"   {name} ({etype}): {count} 条")

    elif args.command == "digest":
        if args.file:
            try:
                text = Path(args.file).read_text(encoding="utf-8")
            except OSError as exc:
                print(f"❌ 读取文件失败: {exc}")
                return 1
        elif args.text:
            text = args.text
        else:
            print("❌ 需要提供文本参数或 --file 文件路径")
            return 1
        result = mem.digest(text, apply=args.apply, max_facts=args.max,
                            verified=args.verified)
        mode_label = "LLM 摘要" if result["mode"] == "llm" else "规则式提取"
        print(f"🧠 沉淀模式: {mode_label} | 提取 {len(result['facts'])} 条要点")
        for i, fact in enumerate(result["facts"], 1):
            cat_icon = {"preference": "⭐", "decision": "✅", "config": "⚙️",
                        "project": "📁", "event": "📅"}.get(fact.get("category"), "📌")
            print(f"  {i}. {cat_icon} [{fact.get('category', 'event')}] 重要{fact.get('importance', 5)}")
            print(f"     {fact['content']}")
        if args.apply:
            print(f"✅ 已写入 {len(result['applied'])} 条记忆（默认未验证，可用 verify 确认）")
        else:
            print("💡 预览模式（未写入），确认后加 --apply 写入记忆")

    elif args.command == "verify":
        result = mem.verify(args.memory_id)
        print(f"✅ 已执行验证: {result['id']}")

    elif args.command == "prune":
        result = mem.prune(dry_run=args.dry_run, room=args.room)
        if result["dry_run"]:
            print(f"🔍 预演：将淘汰 {result['expired_count']} 条记忆")
            for mid in result["expired_ids"]:
                print(f"   - {mid}")
            if result["expired_count"] and not args.yes:
                print("执行删除请加 --yes（非预演模式）")
        else:
            print(f"🗑️ 已归档 {result['archived']} 条、删除 {result['deleted']} 条")

    elif args.command == "forget":
        result = mem.forget(args.memory_id)
        print(f"🗑️ 已删除: {result['id']}")

    elif args.command == "stats":
        stats = mem.stats()
        print(f"📊 记忆统计：共 {stats['total']} 条")
        print(f"   已验证: {stats['verified']} | 未验证: {stats['unverified']} | "
              f"平均重要性: {stats['avg_importance']}")
        print(f"   🔥热记忆(高频): {stats['hot']} | 🧊冷记忆(低频): {stats['cold']}")
        for rid, info in stats["rooms"].items():
            print(f"   {info['name']}({rid}): {info['count']} 条")
        print(f"   存储: {stats['store_bytes']} 字节 | 索引: {stats['index_path']}")

    elif args.command == "rooms":
        for room in mem.list_rooms():
            print(f"{room['icon']} {room['name']}({room['id']}): {room['count']} 条 | "
                  f"保留 {room['retention_days']} 天")
    return 0


if __name__ == "__main__":
    sys.exit(main())
