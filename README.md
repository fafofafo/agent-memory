# Agent Memory —— 智能体记忆/学习/进化系统（DSH 落地版，原 Hermes Lite）

基于 Hermes v2.1 五层记忆架构的设计理念，**修正其 P0/P1 缺陷**后的轻量可运行实现。

## 设计理念（保留的精华）

| 层次 | 理念 | 落地方式 |
|---|---|---|
| L0 入口层 | **No Execution, No Memory**（执行验证后才算数） | `remember` 默认 `execution_verified=False`，`verify` 命令手动确认 |
| L1 存储层 | 分类存储 | 5 个房间目录 + Obsidian 兼容 Markdown（YAML frontmatter） |
| L2 检索层 | 语义检索 | 关键词 + 中文 n-gram 重叠 + 加权打分（真实计算，无伪造指标） |
| L3 知识库 | 结构化 Wiki | Markdown + YAML frontmatter，双向链接预留 |
| L4 技能层 | 频次追踪 | access_count / last_accessed 自动更新 |

## 修正了 Hermes v2.1 的哪些问题

- ✅ **真实检索**：替换占位桩，打分可复现、可测试（原版 `_semantic_search_in_rooms` 返回硬编码 0.85）
- ✅ **无伪造指标**：删掉永远返回 95%~97% 的假召回率，stats 只报告真实计数
- ✅ **真实淘汰**：`find_expired` 真实查找过期记忆，归档后删除（原版返回空列表 + `pass`）
- ✅ **脱敏落盘**：密码/token/密钥原文不写入任何文件（原版明文存密码）
- ✅ **配置单一来源**：YAML 被真正加载（原版用 `json.load` 解析 `.yaml` 且配置与代码脱节）
- ✅ **默认未验证**：`execution_verified` 默认 `False`，未验证记忆 7 天淘汰（原版默认 `True` 违背自身原则）
- ✅ **砍掉虚假层**：移除未实现的异步同步/分布式/MCP 桩代码

## 快速开始

```bash
cd agent-memory

# 写入记忆（默认未验证；--verified 表示已经过执行验证）
python3 hermes_lite.py remember "决定采用 PostgreSQL，端口 5432" \
    --category decision --importance 8 --verified --source "会议"

# 检索（关键词 + 向量混合，RRF 融合）
python3 hermes_lite.py recall "数据库端口"
python3 hermes_lite.py recall "偏好" --room prefs

# 纯向量检索（显示余弦相似度）
python3 hermes_lite.py vsearch "生产环境的数据库选型"

# 向量后端状态
python3 hermes_lite.py vectors

# 执行验证一条记忆
python3 hermes_lite.py verify mem_20260817_113106_c04b

# 淘汰预演 / 执行
python3 hermes_lite.py prune --dry-run
python3 hermes_lite.py prune --yes

# 统计 / 房间 / 删除
python3 hermes_lite.py stats
python3 hermes_lite.py rooms
python3 hermes_lite.py forget <memory_id> --yes

# 自动沉淀：从对话文本提取要点（默认预览，--apply 写入）
python3 hermes_lite.py digest "我们决定采用 Redis 做缓存，配置在 6379 端口"
python3 hermes_lite.py digest --file conversation.txt --apply
```

## 自动沉淀（digest）

从对话/文本中自动提取可长期记忆的要点，**复用完整记忆链路**（脱敏 → 去重合并 → 默认未验证）。

| 模式 | 说明 | 启用 |
|---|---|---|
| **LLM 摘要** | 质量最高，可理解语义（✅ 已激活：DeepSeek） | `.env` 配 `DEEPSEEK_API_KEY`（国内直连） |
| **规则式提取** | 零依赖，免费 | 无 key 时自动回退 |

- 提取类别：决定/偏好/配置/项目/事件，自动分类 + 重要性
- 工作流：先预览（不写入）→ 确认后 `--apply` 写入
- `--verified` 可在写入时标记已验证（否则默认未验证，7 天短留）
- LLM 端点可自定义：`DIGEST_LLM_BASE_URL` / `DIGEST_LLM_MODEL`（OpenAI 兼容）

## 向量检索层（可插拔后端）

检索默认走**混合模式**：关键词打分 + 向量余弦 → RRF 融合排序。

| 后端 | 说明 | 启用方式 |
|---|---|---|
| `siliconflow` | 硅基流动 BGE-M3（1024 维，✅ 当前激活） | `data/.env` 写入 `SILICONFLOW_API_KEY` |
| `jina` | Jina Embeddings v3（1024 维，国际网络，已配 key 待网络） | `data/.env` 写入 `JINA_API_KEY` |
| `local` | 零依赖本地哈希向量（词法近似语义） | 无 key 时自动兜底 |

- **key 安全**：只存 `data/.env`（权限 600），不进入代码/索引/输出
- **熔断降级**：远端后端失败一次 → 自动降级 `local` 并持久化熔断记录（`.vector_backend_state.json`），避免每轮重复重试；删除该文件或设 `HERMES_VECTOR_BACKEND=jina` 可恢复
- **增量向量化**：只对新记忆生成向量，缓存在 `data/vectors.json`，不重复调用 API
- **强制切换**：`HERMES_VECTOR_BACKEND=auto|local|jina|siliconflow`

## 数据目录

```
data/                      # 根目录（可用 --root 或 $HERMES_LITE_ROOT 指定）
├── config.yaml            # 单一配置源（房间/映射/检索/淘汰/脱敏规则）
├── .env                   # 向量后端密钥（权限 600，勿提交）
├── index.json             # 记忆索引（含频次、验证标志）
├── vectors.json           # 向量缓存（memory_id → 向量）
├── .vector_backend_state.json  # 熔断状态（远端失败自动降级记录）
├── rooms/                 # 房间说明（prefs/decisions/configs/projects/events）
├── store/                 # 记忆正文（Obsidian 兼容 .md）
└── backups/               # 淘汰归档（prune_时间戳.json）
```

## 核心规则

- **房间保留期限**：prefs 365 天 / decisions 730 天 / configs 365 天 / projects 545 天 / events 90 天
- **关键记忆**（importance=10）：永久保留
- **未验证记忆**：7 天（No Execution, No Memory）
- **低频记忆**：访问 <3 次且超 30 天淘汰
- **脱敏**：密码/API key/token/sk-*/Bearer 自动替换为 `[已脱敏:类型]`，原文不落盘
- **去重合并**：写入内容与已有记忆相似度 ≥85% 时自动合并更新（取更高重要性），记忆库不膨胀
- **冲突检测**：新记忆对某实体持相反断言（决定用 X / 放弃 X）时自动警告
- **重要性自适应**：每 10 次访问 importance+1（上限 10）
- **冷热分层**：访问 ≥5 次的热记忆检索权重 ×1.1（`hot_threshold`/`hot_boost` 可配）
- **原子写入 + 自动备份**：先写临时文件再 rename，每日首次写入自动备份（保留 7 份）

## 记忆图谱（graph）

自动从记忆内容抽取**实体**（专有名词/版本号），建立 实体 ↔ 记忆 多对多关联，存 `data/graph.json`。

```bash
python3 hermes_lite.py graph            # 列出实体（按关联记忆数排序）
python3 hermes_lite.py graph PostgreSQL # 查某实体的关联记忆
python3 hermes_lite.py graph --rebuild  # 全量重建
```

## 加密存储（可选）

`HERMES_ENCRYPT=on`（环境变量或 `.env`）启用 **Fernet AES 加密**：
- 加密对象：`index.json` / `vectors.json` / `graph.json`（store/*.md 保持明文，脱敏已保护）
- 密钥：`.env` 的 `HERMES_MASTER_KEY`，未设置则自动生成到 `data/.master_key`（600 权限）
- 开启后数据文件为密文，重新加载自动解密；测试覆盖读写一致性

## 检索分层

```
查询
 ├─ BM25 词法层    （纯 Python，零依赖：ASCII 词 + 中文 n-gram，Okapi BM25）
 ├─ 向量语义层      （三后端可插拔：siliconflow✅ / jina / local，见上）
 ├─ RRF 融合        （两路排序 Reciprocal Rank Fusion）
 └─ Rerank 精排     （✅ BGE-reranker-v2-m3：对召回候选做相关性精排，过滤假阳性）
```

- Rerank 使用硅基流动 rerank API（`SILICONFLOW_API_KEY`），失败自动进程内熔断回退
- 关闭：`HERMES_RERANK=off`

## 对话流接入（自动沉淀）

`auto_sediment.py` 从 DSH 会话日志自动提取对话要点，经 digest（LLM 摘要）沉淀入库。
**建议约定**：每次对话结束或关键节点后运行一次，本轮决策/偏好/配置自动记忆。

```bash
# 预览最新会话的沉淀要点（不写入）
python3 auto_sediment.py --dry-run

# 确认后写入（默认未验证，可 --verified）
python3 auto_sediment.py --apply

# 指定会话文件 / 直接文本
python3 auto_sediment.py --file /path/session.jsonl --apply
python3 auto_sediment.py --text "决定采用 X，偏好 Y" --apply
```

- 自动提取**用户消息 + 助手回复**（跳过思考链与工具结果）
- LLM 摘要模式（DeepSeek）→ 复用脱敏/去重/未验证链路
- 会话目录可配：`--sessions-dir`

## 测试

```bash
python3 test_hermes_lite.py   # 79 项端到端断言，全部通过
python3 test_stress.py        # 压力测试：150 条记忆（写入 6ms/条、检索 52ms/查询）
python3 auto_sediment.py --dry-run   # 对话流自动沉淀（预览）
```

## 许可

[MIT License](LICENSE)（Copyright (c) 2026 Agent Memory Contributors）。
本系统为独立创作，仅借鉴公开设计理念；基于 MIT 许可的 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 平台运行。可自由使用、修改、分发、商用（含销售）。

## 环境要求

- Python 3.10+
- PyYAML（缺失时自动回退内嵌默认配置）
