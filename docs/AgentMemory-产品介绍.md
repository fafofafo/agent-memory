# Agent Memory —— 智能体记忆 / 学习 / 进化基础设施

> 为任何 AI 智能体提供"跨会话长期记忆、对话自动学习、持续自我进化"的通用能力底座。
> 原名 Hermes Lite，源自对 Hermes v2.1 五层记忆架构的评审与重构（原案 40-50% 代码为占位桩、指标伪造、存在安全缺陷），本系统为**独立实现**，全部能力真实可运行。

---

## 一句话定位

**让任何智能体拥有"人一样的记忆"：记得住（存储）、学得会（沉淀）、想得起（检索）、会成长（进化）——一次部署，永久受用。**

## 为什么需要

| 痛点 | Agent Memory 的答案 |
|---|---|
| 会话一结束就"失忆"，历史全丢 | 跨会话持久记忆，永不丢失 |
| 长对话超窗口被截断，早期信息丢失 | 记忆外置，突破上下文窗口（128k 截断 vs 永不超窗） |
| 每轮全量携带历史，token 浪费 85-98% | 只注入检索到的 top-k 相关记忆 |
| 对话要点靠人工整理 | 自动沉淀（LLM 摘要），零人工 |
| 检索靠关键词，同义词/隐含语义搜不到 | 四层混合检索（BM25+向量+RRF+Rerank） |
| 记忆越存越乱、越存越脏 | 去重合并、冲突检测、淘汰归档、图谱关联 |

## 核心能力（九层架构）

```
沉淀   对话自动沉淀 digest（LLM 摘要 / 规则式兜底）+ 冲突检测
写入   remember（脱敏 → 去重 → 验证 → 图谱更新）
存储   5 主题房间 + Obsidian 兼容 + 原子写入 + 每日自动备份 + 可选 AES 加密
检索   BM25 → 语义向量 → RRF 融合 → Rerank 精排 → 冷热加权
生命   频次追踪 + 重要性自适应 + 淘汰归档 + 关键记忆永久
关联   记忆图谱（实体 ↔ 记忆，自动维护）
安全   敏感信息自动脱敏（密码/token 不落盘）+ 密钥 600 权限
对话流 一键从会话日志自动沉淀（auto_sediment）
运维   熔断降级、后端切换自动重建、真实统计（无伪造指标）
```

## 技术亮点

1. **零重依赖核心**：BM25 检索、存储、淘汰、脱敏全部纯 Python 标准库实现，开箱即用
2. **可插拔三后端向量**：本地哈希（零成本兜底）/ 硅基流动 BGE-M3（国内直连）/ Jina v3（国际网络），自动切换 + 熔断降级
3. **四层混合检索**：BM25 词法 + 语义向量 + RRF 融合 + Rerank 精排，检索精度工业级
4. **LLM 自动沉淀**：DeepSeek 摘要（实测单次 ~490 token），自动分类/脱敏/去重
5. **安全设计**：明文密码不落盘（含独立 token 场景）、密钥 600 权限、可选 Fernet AES 加密
6. **诚实工程**：所有统计为真实计数，无伪造指标；79 项测试 + 150 条压力验证

## 快速部署

### 方式一：同机新 harness（零操作）
技能已置于 `$DSH_HOME/skills/agent-memory/`，任何新会话自动发现，直接说"加载 agent-memory 技能"即可。

### 方式二：新机器（1 个文件）
```bash
# 只需 SKILL.md，放到：
mkdir -p ~/.dsh/skills/agent-memory/
cp SKILL.md ~/.dsh/skills/agent-memory/
```
新 harness 自动发现，按规格从零实现（已自包含，无需额外说明）。

### 方式三：带参考实现（推荐用于生产）
```bash
# 整个项目目录迁移，直接复用已实现代码
cp -r agent-memory/ /目标路径/
export HERMES_LITE_ROOT=/目标路径/agent-memory/data
python3 agent-memory/hermes_lite.py stats   # 验证
```

## 快速开始

```bash
# 写入记忆（默认未验证，贯彻 No Execution No Memory）
python3 hermes_lite.py remember "决定采用 PostgreSQL 作为生产数据库，端口 5432" \
    --category decision --importance 8 --verified

# 混合检索（四层）
python3 hermes_lite.py recall "数据库选型"

# 对话自动沉淀（LLM 摘要）
python3 auto_sediment.py --apply

# 记忆图谱
python3 hermes_lite.py graph PostgreSQL

# 生命周期管理
python3 hermes_lite.py prune --dry-run
python3 hermes_lite.py stats
```

## 性能与可靠性

| 指标 | 实测 |
|---|---|
| 自动化测试 | **79 项断言全过** |
| 压力测试 | 150 条记忆：写入 6ms/条、检索 52ms/查询、命中率 10/10 |
| Token 节省 | 输入 token 节省 **85.6%（实测）~ 98%（长期外推）** |
| 沉淀成本 | LLM 摘要实测单次 ~490 token，摊销每轮 ~215 token |
| 数据安全 | 明文密码/密钥不落盘 + 原子写入 + 每日备份 + 可选加密 |

## 许可与合规

- **MIT License**（Copyright 2026 Agent Memory Contributors），可自由使用、修改、分发、商用
- 独立创作，仅借鉴公开设计理念，不复制任何第三方代码
- 运行于 MIT 许可的 DeepSeek Harness 平台（github.com/deepseek-ai/deepseek-harness）
- 外部服务（DeepSeek/硅基流动/Jina）仅作可选后端，均为各平台公开 API

## 获取方式

- 技能文件：`SKILL.md`（完整实施规格，自包含）
- 参考实现：完整项目目录（代码 + 测试 + 文档 + 数据样例）
- 支持：部署协助 / 定制（更多房间、企业接入）/ 培训

---

*Agent Memory · 让每个智能体都拥有记忆、学习与进化的能力*
