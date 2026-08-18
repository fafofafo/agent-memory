---
name: agent-memory
description: 为任何智能体建立长期记忆、自动学习与自我进化能力的通用基础设施（原 hermes-lite）：跨会话记忆、对话自动沉淀（digest）、混合语义检索（BM25+向量+Rerank）、记忆图谱、淘汰与加密。当用户要求实现/复现/搭建记忆系统、或需要长期记忆、对话自动沉淀、语义检索、知识积累与自我进化能力时使用本技能。包含完整实施规格、关键设计决策与验收标准，新 harness 实例加载后即可按步骤复现，无需额外说明。
whenToUse: 用户提出要实现记忆系统；要求搭建"Agent Memory"、记忆/学习/进化基础设施或"五层记忆"；需要为智能体增加长期记忆、对话自动沉淀、混合检索（BM25+向量+Rerank）、记忆淘汰与加密能力；或要求评审/改进记忆系统架构。
metadata:
  license: MIT
  version: 3.0
  origin: 源自 hermes-lite（Hermes v2.1 评审后重构的独立系统），更名以体现通用定位
---

# Agent Memory — 智能体记忆/学习/进化基础设施（实施规格）

> 原名 **Hermes Lite**（源自对 Hermes v2.1 五层记忆指南的评审与重构）。本系统早已超越"轻量版 Hermes"，是面向**所有智能体**的通用记忆、自动学习与自我进化能力底座，故更名 `agent-memory`。历史名称保留在文档中以便溯源。

## 0. 背景与设计哲学

本系统源自对"Hermes v2.1 五层记忆指南"的评审与修正。原指南 40-50% 代码为占位桩、核心指标伪造（召回率恒返回 95-97%）、明文存密码、YAML 从未被加载。本规格保留其**设计理念**，全部实现为**真实可运行代码**。

核心原则（必须遵守）：
1. **No Execution, No Memory**：`execution_verified` 默认 `False`，未验证记忆 7 天淘汰；`verify` 命令人工确认。
2. **敏感信息不落盘**：密码/token/API key 等自动脱敏为 `[已脱敏:类型]`，原文写入任何文件即视为缺陷。
3. **配置单一来源**：所有房间/映射/检索参数只在 `config.yaml`，代码加载它，禁止硬编码副本。
4. **无伪造指标**：任何统计必须是真实计数；禁止输出恒为固定范围的"估算召回率"。
5. **零依赖优先**：核心能力（BM25/存储/淘汰）纯标准库实现；外部服务（向量/LLM/Rerank）做成可插拔后端 + 熔断降级。

## 1. 目标形态

```
沉淀   digest（LLM 摘要优先 / 规则式兜底）+ 冲突检测
写入   remember（脱敏 → 去重合并 → 冲突提示 → 默认未验证 → 图谱更新）
存储   5 房间（prefs/decisions/configs/projects/events）+ Obsidian Markdown
       + 原子写入 + 每日自动备份 + 可选 AES 加密
检索   BM25（纯 Python）→ 向量（local 哈希 / siliconflow BGE-M3 / jina v3）
       → RRF 融合 → Rerank 精排（BGE-reranker-v2-m3）→ 冷热加权
生命   频次追踪 + 重要性自适应（每 10 次访问 +1，上限 10）+ 淘汰归档 + 关键记忆永久
关联   记忆图谱（实体 ↔ 记忆，自动维护）
对话流 auto_sediment.py（从会话日志自动沉淀）+ CLI 全命令
```

## 2. 目录结构

```
agent-memory/           # 项目目录名（与参考实现一致；功能无影响，可按部署环境自定）
├── hermes_lite.py        # 单文件核心（CLI + 库），所有类在此
├── config.yaml           # 单一配置源
├── test_hermes_lite.py   # 端到端测试（≥78 项断言）
├── test_stress.py        # 压力测试（150 条记忆）
├── auto_sediment.py      # 会话日志 → 自动沉淀
├── README.md
└── data/                 # 运行时数据（可用 --root 或 $HERMES_LITE_ROOT 指定）
    ├── config.yaml       # 复制到数据根（或被代码加载）
    ├── .env              # 密钥（权限 600）：JINA_API_KEY / SILICONFLOW_API_KEY / DEEPSEEK_API_KEY
    ├── index.json        # 记忆索引（含频次、验证标志）
    ├── vectors.json      # 向量缓存 {"backend": name, "vectors": {id: vec}}
    ├── graph.json        # 记忆图谱 {"entities": {name: {type, memory_ids}}}
    ├── .vector_backend_state.json  # 熔断状态（远端失败自动降级记录）
    ├── .master_key       # AES 主密钥（ENCRYPT=on 时自动生成，600 权限）
    ├── rooms/            # 房间说明
    ├── store/            # 记忆正文（Obsidian 兼容 .md，YAML frontmatter）
    └── backups/          # 淘汰归档 + 每日自动备份
```

## 3. 实施步骤（按序执行，每阶段跑测试）

### Phase 1：存储层 + 入口层
- `HermesLite` 类：`__init__(root)` 初始化目录、加载 YAML 配置（`yaml.safe_load`，缺失回退内嵌默认）、加载 index.json。
- `remember(text, category, importance, verified, source)`：**默认未验证**；`_redact()` 脱敏（正则模式见 §5）；`_find_duplicate()` 相似度 ≥0.85 时合并更新（重要性取 max，不新增）；`_find_conflicts()` 正反断言检测；写入 store/{id}.md（YAML frontmatter）+ index.json；`_invalidate_bm25()`。
- `verify(memory_id)`：标记 `execution_verified=True`。
- 记忆 ID 格式：`mem_YYYYMMDD_HHMMSS_xxxx`。

### Phase 2：生命周期
- 房间保留期限：prefs 365 / decisions 730 / configs 365 / projects 545 / events 90 天（config.yaml 配置）。
- 淘汰 `prune(dry_run)`：关键记忆（importance=10）永久；未验证 7 天；低频（访问<3 次且 >30 天）；过期归档到 backups/prune_*.json 后删除。**必须真实查找+删除，禁止空壳**。
- `stats()`：总数/房间分布/验证数/热冷/平均重要性/字节数（全部真实）。
- 原子写入：写临时文件 + `os.replace`；每日首次写入自动备份（保留 7 份）。

### Phase 3：检索（BM25 + 向量 + RRF）
- `tokenize_terms(text)`：ASCII 词（小写）+ 中文 2/3-gram。
- `BM25Index`：纯 Python Okapi BM25（k1=1.5, b=0.75），`search(query)` 返回全库降序；`_keyword_rank` 按房间过滤，热记忆（access_count≥阈值）×1.1。
- 向量后端抽象（可插拔）：
  - `LocalHashVectorizer`：零依赖兜底，字符 n-gram MD5 哈希 → 2048 维归一化向量。
  - `JinaVectorizer`（`https://api.jina.ai/v1/embeddings`，jina-embeddings-v3，1024 维，国际网络）。
  - `SiliconFlowVectorizer`（`https://api.siliconflow.cn/v1/embeddings`，BAAI/bge-m3，1024 维，国内直连；query 加前缀"为这个句子生成表示以用于检索相关文章："）。
  - key 来源：环境变量 > `data/.env`；后端选择 `HERMES_VECTOR_BACKEND=auto|local|jina|siliconflow`；auto 优先 jina（有 key），其次 siliconflow，最后 local。
  - **熔断降级**：远端失败一次 → 持久化到 `.vector_backend_state.json` → 降级 local，并用 local 重试补齐；删除状态文件或显式指定可恢复。
  - **后端切换自动重建**：vectors.json 带 backend 标记，切换后端（维度/语义不同）时清空缓存重新生成。
- `recall(query, room, top_k)`：关键词排名 + 向量召回（余弦 ≥ 阈值：local 0.30 / 远端 0.35，按房间过滤）→ `rrf_merge([kw_ids, vec_ids])` 融合。结果含 kw_score/vec_score。

### Phase 4：Rerank + 图谱 + 加密
- `SiliconFlowReranker`（`https://api.siliconflow.cn/v1/rerank`，BAAI/bge-reranker-v2-m3）：RRF 后取 top-20 候选精排 → top-k；失败进程内熔断（`_rerank_ok=False`），不影响基础检索；`HERMES_RERANK=off` 关闭。
- `GraphStore`（graph.json）：`extract_entities()` 规则式抽取（大写开头英文词排除停用词表 + 版本号 `\d+\.\d+` / `v\d+\.\d+`）；remember/合并/删除时增量维护；CLI：`graph` / `graph <entity>` / `graph --rebuild`。
- 加密（`get_encryption`）：`HERMES_ENCRYPT=on` 时 Fernet AES 加密 index/vectors/graph；key 从 `HERMES_MASTER_KEY` 或自动生成 `data/.master_key`（600）；store/*.md 保持明文（脱敏已保护）；cryptography 缺失时优雅降级。**默认 off**。

### Phase 5：自动沉淀 + 对话流
- `RuleDigester`（零依赖兜底）：正则提取 决定/偏好/配置/项目/事件，格式"标签：值"。
- `LLMDigester`（OpenAI 兼容 chat completions，默认 DeepSeek `https://api.deepseek.com`，deepseek-chat）：system prompt 要求输出 JSON 数组（content/category/importance），敏感信息不输出原文；`response_format: json_object`；记录 `last_usage`（真实 token 成本）；失败回退规则式。
- `HermesLite.digest(text, apply)`：提取 → 预览 → `--apply` 时逐条走 remember 全链路（默认未验证）。
- `auto_sediment.py`：解析 DSH 会话日志（`user/message` + `assistant/message` 的 text，跳过思考链/工具结果；zstd 用 `zstd -dc` 解压；`--latest` 自动找最新 session）→ digest；`--dry-run` 预览 / `--apply` 写入。

### Phase 6：测试与验收
- `test_hermes_lite.py`：≥78 项断言，覆盖：配置加载、脱敏（明文不落盘）、去重合并、冲突检测、验证原则、淘汰（含关键记忆永久）、BM25 命中/零命中、向量缓存/后端切换/熔断、RRF、Rerank 熔断、图谱、加密读写一致、digest 预览/应用。
- `test_stress.py`：150 条唯一内容记忆（避免被去重合并）：写入 ≤10ms/条、检索 ≤100ms/查询、命中率 10/10（参考打印值，非硬性断言，见 §7.2）。
- 验收演示：检索无字面重叠的语义查询能命中；`grep -r "明文密码" data/` 为空；`prune --dry-run` 输出真实过期数。

## 4. CLI 命令清单

```
remember TEXT [--category preference|decision|config|project|event|discussion|idea|general]
                [--importance 1-10] [--verified] [--source S]
recall QUERY [--room R] [--top-k N]        # BM25+向量+RRF+Rerank 混合检索
vsearch QUERY [--top-k N]                  # 纯向量检索（显示余弦）
verify ID                                  # 执行验证
prune [--dry-run] [--room R] [--yes]       # 淘汰（归档+删除；--dry-run 只统计；--yes 供确认提示用）
forget ID [--yes]                          # 删除单条（--yes 为兼容参数，实际直接删除）
digest TEXT|--file F [--apply] [--max N] [--verified]   # 自动沉淀
graph [entity] [--top N] [--rebuild]       # 记忆图谱
stats                                      # 真实统计（含热/冷）
rooms                                      # 房间列表
vectors                                    # 向量后端状态（含熔断/Rerank 状态）
```

## 5. 关键设计决策（复现时不得省略）

| 决策 | 理由 |
|---|---|
| 脱敏正则 5 条全集见 §9.5，含系动词"是/为"分支 | 实测"密码是 hunter2"用旧正则只捕获到"是"，密码漏网；值捕获组用 `([^\s,，。;；]+)` 防吞标点 |
| 去重合并阈值 0.85（SequenceMatcher） | 防记忆膨胀；短内容不参与匹配（len<5） |
| 冲突检测正/负断言正则见 §9.6 | 规则式零成本；LLM 检测更准但每次写入都调 API 太贵 |
| BM25 替代启发式打分 | 对词频/文档长度/稀有词更敏感，区分度显著提升（实测精确查询分 5→25） |
| RRF 融合（k=60）而非分数加权 | 两路分数尺度不同，rank 融合更鲁棒 |
| 向量阈值过滤（0.30/0.35）而非全量召回 | 防止无关查询被向量召回污染结果 |
| 重要性自适应每 10 次访问 +1 | 高频记忆自然升权，上限 10 保关键记忆语义 |
| AES 默认 off | 威胁模型：数据已脱敏+600 权限；加密引入 key 丢失风险且文件不可 grep |
| 图谱自动维护、不参与排序 | 记忆量小图谱无网络效应，保留零成本，待规模增长再增强 |

## 6. 环境适配（重要）

- **网络分区**：国际 API（jina/openai/huggingface）可能不可达，国内（siliconflow/dashscope/deepseek）可达。三后端 + 熔断正是为此设计。
- **沙箱**：文件写操作可能被限制在指定工作区；数据根目录必须落在可写区域（如工作区下 `agent-memory/data`），通过 `$HERMES_LITE_ROOT` 指定。
- **密钥安全**：所有 key 只写 `data/.env`（chmod 600），禁止硬编码进代码、禁止打印到任何输出。
- **token 成本透明**：digest 每次沉淀约 250 token 固定系统提示 + 输入 + 输出（DeepSeek 实测单次 ~490 token/5 条要点）；检索注入 top-5 约 300-1000 token/轮，不随记忆总量线性增长。

## 7. 验收标准（全部满足才算完成）

1. `python3 test_hermes_lite.py` 全部通过（≥78 项）。
2. `python3 test_stress.py`：150 条记忆，精确查询命中。耗时指标（写入 ≤10ms/条、检索 ≤100ms/查询）为**参考打印值**，非硬性断言（避免慢机器 flaky）；命中率"10/10"指 10 个查询均有结果。
3. 演示三件事：
   - 语义检索：查询与记忆无字面重叠时能命中——**需配置远端向量 key**（siliconflow/jina）；无 key 时 local 哈希仅演示词法近似（同义词无法匹配），验收时应注明后端。
   - 脱敏：写入"密码是 xxx"后 `grep -r xxx data/` 无结果。
   - 生命周期：未验证记忆 7 天淘汰、关键记忆永久保留（测试断言）。
4. 所有统计数据为真实计数（无伪造指标）。
5. 不依赖任何未安装的第三方库即可完成核心功能（BM25/存储/检索/淘汰纯标准库）。

## 8. 参考实现

本技能对应的完整参考实现位于工作区 `agent-memory/`（`hermes_lite.py` 单文件约 1600 行、79 项测试、150 条压力测试全过）。复现时以本规格为准，参考实现仅用于核对与本附录不一致的极端细节。实现后建议对照 `Token节省实测分析报告v2.md` 理解系统的 token 成本模型。

## 9. 数据格式与配置参考（附录，复现时照此实现）

### 9.1 store/*.md 格式（Obsidian 兼容，YAML frontmatter）

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

frontmatter 字段顺序固定为：id, category, room, importance, execution_verified, access_count, last_accessed, source, created_at, redacted（redacted 仅在有脱敏时输出，逗号分隔）。

### 9.2 index.json 条目 schema

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

index.json 顶层为条目数组；写入用原子写（临时文件 + os.replace）+ 每日首次自动备份到 backups/auto_index.json.YYYYMMDD.bak（保留 7 份）。淘汰归档文件格式：`backups/prune_YYYYMMDD_HHMMSS.json` = `{"archived_at": ISO时间, "memories": [完整条目...]}`。

### 9.3 config.yaml 完整参考值

```yaml
rooms:            # 保留期（天）；展示字段 name/description/icon 可自定
  prefs: 365      # 偏好
  decisions: 730  # 决策
  configs: 365    # 配置
  projects: 545   # 项目
  events: 90      # 事件
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
  redact_patterns: （见 9.5）
```

> 注：weight_importance/weight_frequency/weight_verified 为历史启发式参数，实际检索路径使用 BM25+RRF+hot boost+min_score，这些权重字段保留兼容但不由检索使用。

### 9.4 DSH 会话日志结构（auto_sediment 解析目标）

```json
{"type":"user/message","seq":5,"time":1786932396089,"data":{"content":[{"type":"text","text":"用户消息"}]}}
{"type":"assistant/message","seq":6,"time":...,"data":{"message":{"role":"assistant","content":[{"type":"reasoning","text":"思考链（跳过）"},{"type":"text","text":"助手回复"}]}}}
{"type":"tool/call","seq":7,"time":...,"data":{"name":"bash","arguments":"{\"command\":\"...\"}"}}
{"type":"tool/result","seq":8,"time":...,"data":{"message":{"source":{"kind":"tool"},"content":[{"type":"tool-result","toolCallId":"...","content":[{"type":"text","text":"工具输出（跳过）"}]}]}}}
```

提取规则：`user/message` 取 `data.content[].text`；`assistant/message` 取 `data.message.content[]` 中 `type=="text"`（**跳过** `reasoning`）；**跳过** `tool/call` 与 `tool/result`。拼接为"用户: …\n助手: …"，截断至 8000 字符后送入 digest。zstd 压缩的会话文件用 `zstd -dc` 解压到 stdout 再解析。

### 9.5 脱敏正则全集（5 条，label 推断）

```python
# 模式 → 脱敏标签
r"((?:密码|口令|passwd|password)(?:\s*(?:是|为|[:：=])\s*|\s+))([^\s,，。;；]+)"      # password
r"((?:api[_-]?key|apikey|access[_-]?key|密钥)(?:\s*(?:是|为|[:：=])\s*|\s+))([^\s,，。;；]+)"  # api_key
r"((?:token|secret|授权码)(?:\s*(?:是|为|[:：=])\s*|\s+))([^\s,，。;；]+)"          # token
r"(sk-[A-Za-z0-9_\-]{8,})"                                                        # api_key
r"(Bearer\s+[A-Za-z0-9_\-\.]{10,})"                                               # token
```

替换逻辑：有前缀捕获组（第 1 组）时保留前缀、值替换为 `[已脱敏:label]`；无前缀组时整体替换为 `[已脱敏:label]`。**判定依据是捕获组数量 ≥2**（前缀+值模式）才保留前缀；单捕获组模式（sk-xxx / Bearer xxx）必须**整体替换**——⚠️ 参考实现旧版曾把整个匹配当前缀保留导致明文残留（`sk-abc123secret[已脱敏:api_key]`），复现时勿照抄该逻辑，以本附录为准（已修复并测试覆盖）。值捕获组用 `([^\s,，。;；]+)`（**不是** `\S+`，避免吞掉中文标点）。执行顺序按表自上而下，命中即记录标签到 `redacted` 字段。关键：**"密码是 hunter2"这类带系动词的写法必须能脱敏**——`(?:\s*(?:是|为|[:：=])\s*|\s+)` 分支覆盖"密码：x"、"密码是 x"、"密码 x"三种形态。

### 9.6 冲突检测正则

```python
pos = r"(?:决定|选择|采用|使用|选用|用)\s*(?:了|的)?\s*([A-Za-z0-9_\-.]+)"   # 正断言
neg = r"(?:放弃|不用|弃用|反对|拒绝|移除|取消|停止)\s*(?:了|的)?\s*([A-Za-z0-9_\-.]+)"  # 负断言
```

新文本的 neg ∩ 旧记忆的 pos（或反向）→ 冲突，输出 {memory_id, entity, type, content}。

### 9.7 recall 评分细节

- 关键词分 kw_score = BM25 分数（>0 即候选）；热记忆（access_count≥hot_threshold）×hot_boost。
- 向量分 vec_score = 余弦（≥阈值 local 0.30 / 远端 0.35 才进入融合，且按房间过滤）。
- 融合：`rrf_merge([kw_ids, vec_ids], k=60)`。
- display_score = kw_score（>0 时）否则 vec_score×3；kw=0 且 vec < min_score/3 时丢弃。
- 每次命中结果更新 entry.access_count+=1、last_accessed、`_save_index()`；access_count % 10 == 0 且 importance<10 时 importance+1。
