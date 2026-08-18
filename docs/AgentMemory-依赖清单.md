# Agent Memory 依赖与配置清单

> 本清单列出运行 Agent Memory 所需的**全部外部服务（模型 + Key）、本地依赖、环境变量与网络要求**，以及每种 Key 的具体用途、必需性与获取渠道。**本文件不含任何真实 Key 值**，Key 统一存放于 `data/.env`（权限 600）。

---

## 一、外部 API 服务（模型 + Key）

### 1. LLM 摘要 —— 对话自动沉淀（digest）

| 项 | 说明 |
|---|---|
| **服务** | DeepSeek API（`api.deepseek.com`，国内直连） |
| **Key 变量** | `DEEPSEEK_API_KEY` |
| **模型** | `deepseek-chat`（DeepSeek V4 Flash） |
| **用途** | digest 自动沉淀时，从对话文本提取记忆要点（LLM 摘要模式，质量最高） |
| **必需性** | 🟡 可选 —— 无 Key 时自动回退**规则式提取**（零成本但质量降级） |
| **获取渠道** | [platform.deepseek.com](https://platform.deepseek.com) 注册充值，按 token 计费 |
| **可替代** | 任何 OpenAI 兼容端点：`DIGEST_LLM_BASE_URL` + `DIGEST_LLM_MODEL` 覆盖（如硅基流动 / 阿里云百炼） |

### 2. 语义向量 —— 向量检索（核心语义能力）

| 项 | 说明 |
|---|---|
| **服务 A** | 硅基流动（`api.siliconflow.cn`，**国内直连**） |
| **Key 变量 A** | `SILICONFLOW_API_KEY` |
| **模型 A** | `BAAI/bge-m3`（1024 维） |
| **服务 B** | Jina AI（`api.jina.ai`，**需国际网络**） |
| **Key 变量 B** | `JINA_API_KEY` |
| **模型 B** | `jina-embeddings-v3`（1024 维） |
| **用途** | 记忆内容向量化 + 查询向量化 → 余弦相似度语义检索 |
| **必需性** | 🟡 可选 —— 无 Key 时回退**本地哈希向量**（零成本、零网络，但仅词法近似，同义词无法匹配） |
| **选择优先级** | `auto` 模式：Jina → 硅基流动 → 本地；远端失败自动**熔断降级**本地 |
| **获取渠道** | [siliconflow.cn](https://siliconflow.cn) 注册送免费额度；[jina.ai](https://jina.ai) 免费额度 |

### 3. Rerank 精排 —— 检索质量最终把关

| 项 | 说明 |
|---|---|
| **服务** | 硅基流动 rerank API（`api.siliconflow.cn`，国内直连） |
| **Key 变量** | **复用** `SILICONFLOW_API_KEY`（同一个 Key） |
| **模型** | `BAAI/bge-reranker-v2-m3` |
| **用途** | 对 BM25+向量召回的 top-20 候选做相关性精排，输出最终 top-k（过滤假阳性） |
| **必需性** | 🟢 低 —— `HERMES_RERANK=off` 可关；调用失败自动跳过，不影响基础检索 |

---

## 二、本地运行依赖

| 依赖 | 版本 | 用途 | 必需性 |
|---|---|---|---|
| Python | 3.10+（实测 3.12） | 运行时 | ✅ 必需 |
| PyYAML | 任意 | 加载 `config.yaml` | 🟡 可选（缺失自动回退内嵌默认配置） |
| cryptography | 任意 | 仅 `HERMES_ENCRYPT=on` 时的 AES 加密 | 🟢 可选（默认 off） |
| zstd 命令 | 任意 | 仅 `auto_sediment.py` 解压 `.zstd` 会话日志 | 🟢 可选（也可先手动解压） |
| — | — | **核心功能零第三方依赖**：BM25 检索、存储、淘汰、脱敏、冲突检测全部 Python 标准库 | ✅ |

---

## 三、环境变量清单

| 变量 | 默认 | 用途 |
|---|---|---|
| `HERMES_LITE_ROOT` | `~/.hermes-lite` | 数据根目录（记忆库位置；也可用 `--root` 参数） |
| `HERMES_VECTOR_BACKEND` | `auto` | 向量后端：`auto` / `local` / `jina` / `siliconflow` |
| `HERMES_RERANK` | `on` | Rerank 精排开关：`on` / `off` |
| `HERMES_ENCRYPT` | `off` | 数据加密开关：`on` / `off` |
| `HERMES_MASTER_KEY` | 自动生成 | 加密主密钥（仅 `HERMES_ENCRYPT=on` 时；未设则自动生成到 `data/.master_key`） |
| `DEEPSEEK_API_KEY` | — | LLM 摘要 Key（见上） |
| `SILICONFLOW_API_KEY` | — | 向量 + Rerank Key（见上） |
| `JINA_API_KEY` | — | 向量 Key（国际网络，见上） |
| `DIGEST_LLM_BASE_URL` | `https://api.deepseek.com` | LLM 摘要端点覆盖（OpenAI 兼容） |
| `DIGEST_LLM_MODEL` | `deepseek-chat` | LLM 摘要模型覆盖 |

> Key 既可设环境变量，也可写入 `data/.env`（优先级：环境变量 > .env 文件）。

---

## 四、网络要求

| 网络环境 | 可用服务 | 不可用时表现 |
|---|---|---|
| 国内网络 | ✅ DeepSeek、✅ 硅基流动 | Jina 不可达 → 向量自动熔断降级本地 |
| 国际网络 | ✅ Jina | — |
| 离线 | 无外部服务 | 自动降级：本地哈希向量 + 规则式沉淀，核心功能仍可用 |

**设计保证**：任何外部服务不可用都不会导致系统崩溃——自动降级链路完整（Jina→硅基流动→本地；LLM→规则式；Rerank→跳过）。

---

## 五、三种部署配置建议

| 配置 | 需要的 Key | 获得的能力 |
|---|---|---|
| **最小（零 Key）** | 无 | 全功能可用：BM25 检索、存储、淘汰、去重、脱敏、规则式沉淀、本地向量 |
| **标准（推荐，国内）** | `DEEPSEEK_API_KEY` + `SILICONFLOW_API_KEY` | + LLM 智能摘要 + BGE-M3 语义向量 + Rerank 精排（**完整能力**） |
| **完整（国际）** | 上述 + `JINA_API_KEY` | 语义向量可切换 Jina（网络环境自动选择） |

---

## 六、Key 安全管理规范

1. **只写两处**：环境变量 或 `data/.env`（权限 600，`chmod 600`）
2. **禁止**：硬编码进代码 / 打印到任何输出 / 提交进版本库
3. **独立吊销**：三个 Key（DeepSeek / 硅基流动 / Jina）互相独立，任一泄漏可单独吊销，不影响其他
4. **本清单不含真实 Key**：配置时从各平台控制台获取

---

*Agent Memory · 依赖清单 v1.0（对应技能 version 3.0 / 代码 79 项测试）*
