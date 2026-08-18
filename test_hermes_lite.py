#!/usr/bin/env python3
"""Agent Memory 端到端测试：在临时目录运行，不污染真实数据。"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from hermes_lite import HermesLite, DEFAULT_CONFIG, VectorStore, JinaVectorizer, SiliconFlowReranker

FAILURES = []


def check(name: str, condition: bool, detail: str = ""):
    status = "✅" if condition else "❌"
    print(f"{status} {name}" + (f"  ({detail})" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def days_ago(days: int) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="hermes_lite_test_"))
    try:
        # 配置文件复制到测试根目录
        shutil.copy(Path(__file__).parent / "config.yaml", tmp / "config.yaml")

        mem = HermesLite(root=tmp)

        # ---- 1. 初始化 ----
        check("目录结构创建", all((tmp / d).exists() for d in ("rooms", "store", "backups")))
        check("房间 README 生成", (tmp / "rooms" / "prefs.md").exists())
        check("配置从 YAML 加载（5 房间）", len(mem.config["rooms"]) == 5,
              f"实际 {len(mem.config['rooms'])}")

        # ---- 2. remember ----
        r1 = mem.remember("用户偏好使用中文交流，沟通风格简洁直接",
                          category="preference", importance=8, verified=True, source="WeCom对话")
        r2 = mem.remember("决定采用 PostgreSQL 作为生产数据库，配置在 5432 端口，超时 180 秒",
                          category="decision", importance=8, verified=True)
        r3 = mem.remember("当前通过 WeCom 与 DSH 智能体对话，工作区为 /home/ubuntu/.dsh",
                          category="config", importance=6, verified=True)
        r4 = mem.remember("正在评估 Hermes v2.1 五层记忆架构，已完成代码评审",
                          category="project", importance=7, verified=True)
        r5 = mem.remember("曾咨询 Tavily 搜索 API 是否必要，结论：DSH 内置搜索已够用",
                          category="event", importance=5, verified=True)
        r6 = mem.remember("我的登录密码是 hunter2 请务必记住",
                          category="config", importance=9)
        r7 = mem.remember("未经验证的想法：也许可以把记忆同步到多个节点",
                          category="idea", importance=3)

        check("remember 返回 ID", all(r["id"].startswith("mem_") for r in (r1, r2, r3)))
        check("默认未验证（No Execution, No Memory）", mem._find(r6["id"])["execution_verified"] is False)
        check("verified=True 生效", mem._find(r1["id"])["execution_verified"] is True)
        check("房间映射（decision→decisions）", r2["room"] == "decisions")
        check("idea 归入 events 房间", r7["room"] == "events")

        # ---- 3. 脱敏 ----
        store_text = (tmp / "store" / f"{r6['id']}.md").read_text(encoding="utf-8")
        check("密码已脱敏（原文不落盘）", "hunter2" not in store_text and "已脱敏" in store_text,
              "store 文件含明文密码!")
        check("脱敏类型记录", "password" in mem._find(r6["id"])["redacted"])
        check("非敏感记忆不受影响", "PostgreSQL" in (tmp / "store" / f"{r2['id']}.md").read_text(encoding="utf-8"))

        # 独立 token 脱敏（sk-/Bearer 单组模式：整体替换，禁止明文残留）
        r_token = mem.remember("使用 sk-abc123secret 认证", category="config", importance=5)
        tok_text = (tmp / "store" / f"{r_token['id']}.md").read_text(encoding="utf-8")
        check("独立 sk- token 无明文残留", "sk-abc123secret" not in tok_text
              and "[已脱敏:api_key]" in tok_text, f"实际: {tok_text.strip()[:80]}")
        mem.forget(r_token["id"])

        # ---- 4. recall（真实检索） ----
        hits = mem.recall("数据库端口")
        check("检索：数据库端口命中决策", hits and hits[0]["id"] == r2["id"],
              f"top={[h['id'] for h in hits] if hits else '无'}")
        check("检索：命中项含关键词", hits and "5432" in hits[0]["content"])

        hits2 = mem.recall("搜索 API 工具")
        check("检索：搜索 API 命中 Tavily 事件", hits2 and hits2[0]["id"] == r5["id"],
              f"top={[h['id'] for h in hits2] if hits2 else '无'}")

        hits3 = mem.recall("编程语言偏好", room="prefs")
        check("房间过滤生效", all(h["room"] == "prefs" for h in hits3))

        hits4 = mem.recall("完全无关的随机词xyzq")
        check("无相关记忆返回空", len(hits4) == 0)

        entry = mem._find(r2["id"])
        check("检索更新访问频次", entry["access_count"] >= 1 and entry["last_accessed"] is not None)

        # ---- 5. prune（真实淘汰） ----
        mem._find(r7["id"])["created_at"] = days_ago(10)  # 模拟 10 天前创建
        result = mem.prune(dry_run=True)
        check("预演识别过期（未验证>7天）", r7["id"] in result["expired_ids"],
              f"expired={result['expired_ids']}")
        check("预演不删除", mem._find(r7["id"]) is not None)

        result2 = mem.prune(dry_run=False)
        check("执行淘汰并归档", result2["archived"] == 1 and result2["deleted"] == 1)
        check("淘汰后索引移除", mem._find(r7["id"]) is None)
        archives = list((tmp / "backups").glob("prune_*.json"))
        check("归档文件生成", len(archives) == 1)
        archived = json.loads(archives[0].read_text(encoding="utf-8"))
        check("归档内容完整", len(archived["memories"]) == 1)
        store_file = tmp / "store" / f"{r7['id']}.md"
        check("store 文件已删除", not store_file.exists())

        # 关键记忆（importance=10）永不过期
        r8 = mem.remember("关键决策：生产环境使用 Kubernetes", category="decision",
                          importance=10, verified=True)
        mem._find(r8["id"])["created_at"] = days_ago(4000)  # 11 年前
        check("关键记忆（重要=10）永久保留", r8["id"] not in mem.prune(dry_run=True)["expired_ids"])

        # ---- 7. stats / rooms ----
        stats = mem.stats()
        check("统计总数正确", stats["total"] == 7, f"实际 {stats['total']}")
        check("统计已验证/未验证", stats["verified"] == 6 and stats["unverified"] == 1)
        rooms = mem.list_rooms()
        check("房间列表 5 个", len(rooms) == 5)

        # ---- 7. verify（执行验证原则） ----
        mem.verify(r6["id"])
        check("verify 标记已验证", mem._find(r6["id"])["execution_verified"] is True)

        # ---- 8. forget ----
        mem.forget(r5["id"])
        check("forget 删除单条", mem._find(r5["id"]) is None)

        # ---- 9. 向量层（auto → local，测试环境无 .env） ----
        check("向量后端就绪", mem.vectors.ready() and mem.vectors.backend_name == "local")
        mem.vectors.ensure(mem.index)
        check("向量缓存生成（数量匹配）", len(mem.vectors.vectors) == len(mem.index),
              f"向量 {len(mem.vectors.vectors)} vs 记忆 {len(mem.index)}")
        vhits = mem.vectors.query("数据库", top_k=3)
        check("向量查询返回排序结果", len(vhits) > 0 and isinstance(vhits[0][1], float))
        check("余弦在 [0,1] 区间", all(0.0 <= c <= 1.0 for _, c in vhits))

        # 混合检索路径
        mixed = mem.recall("PostgreSQL 端口")
        check("混合检索正常返回", len(mixed) > 0)
        check("混合检索结果含向量分数键", "vec_score" in mixed[0] and "kw_score" in mixed[0])

        # 熔断降级：模拟远端失败
        vs = VectorStore(tmp)
        vs.backend, vs.backend_name = JinaVectorizer("bad-key", timeout=1), "jina"
        vs._mark_failed("jina")
        check("熔断立即降级 local", vs.backend_name == "local")
        vs2 = VectorStore(tmp)
        check("auto 模式尊重熔断记录", vs2.backend_name == "local",
              f"实际后端 {vs2.backend_name}")

        # ---- 10. BM25 检索 ----
        bm25 = mem._ensure_bm25()
        check("BM25 索引构建", bm25.n == len(mem.index))
        top = bm25.search("PostgreSQL", top_k=1)
        check("BM25 检索命中 PostgreSQL", top and "PostgreSQL" in mem.index[top[0][1]]["content"])
        bm25_hits = mem._keyword_rank("数据库")
        check("BM25 关键词排序正确", bm25_hits and bm25_hits[0][1]["id"] == r2["id"])
        check("BM25 无关查询零命中", mem._keyword_rank("完全无关的随机词xyzq") == [])

        # ---- 11. 去重合并 ----
        dup = mem.remember("决定采用 PostgreSQL 作为生产数据库，配置在 5432 端口，超时 180 秒",
                           category="decision", importance=9, verified=True)
        check("重复记忆自动合并", dup.get("merged") is True and dup["id"] == r2["id"])
        check("合并后不新增条目", mem.stats()["total"] == 6, f"实际 {mem.stats()['total']}")
        check("合并保留更高重要性", mem._find(r2["id"])["importance"] == 9)

        new_id = mem.remember("这是完全不同的新记忆内容测试", category="event")
        check("不同内容不合并", new_id.get("merged") is not True)
        mem.forget(new_id["id"])

        # ---- 12. 原子写入 + 自动备份 ----
        check("无残留临时文件", not (tmp / "index.json.tmp").exists())
        backups = sorted((tmp / "backups").glob("auto_index.json.*.bak"))
        check("自动备份已生成", len(backups) >= 1)
        bak = json.loads(backups[0].read_text(encoding="utf-8"))
        check("备份内容为合法 JSON 列表", isinstance(bak, list) and len(bak) > 0)

        # ---- 13. 自动沉淀 digest（规则式，测试环境无 LLM key） ----
        from hermes_lite import RuleDigester, DigestEngine
        sample = ("我们决定采用 Redis 作为缓存层，配置在 6379 端口。"
                  "用户偏好使用简洁的报告风格。"
                  "我正在推进项目 Alpha 的架构评审。")
        digester = RuleDigester()
        facts = digester.digest(sample)
        check("规则式提取出要点", len(facts) >= 3, f"实际 {len(facts)}: {[f['content'] for f in facts]}")
        cats = {f["category"] for f in facts}
        check("提取分类正确（decision/preference/config/project）",
              {"decision", "preference", "config", "project"} <= cats, f"实际 {cats}")
        check("digest 引擎无 key 时回退规则式", DigestEngine(tmp).mode == "rule")

        # digest 预览不写入
        before = mem.stats()["total"]
        preview = mem.digest(sample, apply=False)
        check("digest 预览不写入", mem.stats()["total"] == before)
        check("预览返回要点", len(preview["facts"]) >= 3)

        # digest 应用写入（走脱敏/去重/未验证链路）
        applied = mem.digest("我的 API 密钥是 sk-abc123secret，决定采用 Redis 作为缓存层",
                             apply=True, max_facts=5)
        check("digest 应用写入", len(applied["applied"]) >= 1)
        added = mem.stats()["total"]
        check("digest 写入后总数增加", added > before, f"before={before} after={added}")
        # 写入的记忆默认未验证
        last = mem.index[-1]
        check("digest 写入默认未验证", last["execution_verified"] is False)
        # 脱敏链生效：sk- 开头的 key 不落盘
        all_content = " ".join(e["content"] for e in mem.index)
        check("digest 写入内容已脱敏", "sk-abc123secret" not in all_content
              and "[已脱敏" in all_content)

        # ---- 14. 向量缓存：新格式解析 + 后端切换自动重建 ----
        vs = VectorStore(tmp)
        check("新格式向量缓存解析（backend 标记）", vs._cached_backend == "local")
        fake_entry = {"id": "mem_test_0001", "content": "测试内容", "room": "events",
                      "importance": 5, "execution_verified": False, "created_at": "2026-01-01T00:00:00+00:00"}
        vs.vectors = {"mem_old_9999": [1.0, 2.0]}   # 模拟旧后端缓存
        vs._cached_backend = "jina"                  # 模拟缓存来自 jina
        vs.ensure([fake_entry])
        check("后端切换自动清空重建", "mem_old_9999" not in vs.vectors
              and "mem_test_0001" in vs.vectors)
        check("重建后缓存标记更新", vs._cached_backend == "local")
        saved = json.loads((tmp / "vectors.json").read_text(encoding="utf-8"))
        check("保存格式含 backend 标记", saved.get("backend") == "local"
              and "vectors" in saved)

        # ---- 15. Rerank 精排（测试环境无 key → 未启用 + 熔断降级） ----
        check("无 key 时 reranker 未启用", mem._reranker is None)
        r = mem.recall("PostgreSQL 端口", top_k=2)
        check("无 rerank 时检索正常", len(r) > 0 and r[0]["rerank_score"] is None)

        rr = SiliconFlowReranker("bad-key", timeout=1)
        try:
            rr.rerank("测试", ["文档一", "文档二"])
            check("rerank 无效 key 抛错", False)
        except RuntimeError:
            check("rerank 无效 key 抛错", True)

        mem._reranker = SiliconFlowReranker("bad-key", timeout=1)
        mem._rerank_ok = True
        mem.recall("项目 配置 记忆 决策")  # 宽查询命中多条 → 触发 rerank → 熔断
        check("rerank 失败进程内熔断", mem._rerank_ok is False)
        mem._reranker = None

        # ---- 16. 冲突检测 ----
        mem.remember("决定采用 Redis 作为缓存层", category="decision", verified=True)
        conflict = mem.remember("放弃 Redis，改用 Memcached", category="decision", importance=8)
        check("矛盾记忆触发冲突警告", len(conflict.get("conflicts", [])) >= 1,
              f"conflicts={conflict.get('conflicts')}")
        check("冲突检测实体正确", any(c["entity"] == "Redis" for c in conflict.get("conflicts", [])))

        # ---- 17. 重要性自适应 ----
        test_entry = mem._find(r2["id"])
        test_entry["access_count"] = 19
        test_entry["importance"] = 9
        mem.recall("PostgreSQL 端口", top_k=1)
        check("重要性自适应（20 次访问 +1，上限 10）",
              mem._find(r2["id"])["importance"] == 10)

        # ---- 18. 冷热分层统计 ----
        stats = mem.stats()
        check("stats 含热/冷统计", "hot" in stats and "cold" in stats)
        check("高频记忆被标记为热", stats["hot"] >= 1, f"hot={stats['hot']}")

        # ---- 19. 记忆图谱 ----
        from hermes_lite import extract_entities
        ents = extract_entities("决定采用 PostgreSQL v2.1 作为数据库")
        check("实体抽取（tech+version）", "PostgreSQL" in ents and "v2.1" in ents)
        mem.graph.build(mem.index)
        check("图谱构建（PostgreSQL 实体存在）",
              "PostgreSQL" in mem.graph.data["entities"])
        linked = mem.graph.memories_for("PostgreSQL", mem.index)
        check("实体关联记忆查询", len(linked) >= 1 and any(r2["id"] == e["id"] for e in linked))
        mem.graph.remove(r2["id"])
        check("图谱移除记忆后关联消失",
              r2["id"] not in mem.graph.data["entities"].get("PostgreSQL", {}).get("memory_ids", []))
        mem.graph.update(mem._find(r2["id"]))

        # ---- 20. AES 加密存储（独立临时目录） ----
        enc_tmp = Path(tempfile.mkdtemp(prefix="hermes_lite_enc_"))
        try:
            os.environ["HERMES_ENCRYPT"] = "on"
            try:
                enc_mem = HermesLite(root=enc_tmp)
                enc_id = enc_mem.remember("加密测试记忆 Redis 6379", category="config",
                                          importance=5, verified=True)["id"]
                raw = (enc_tmp / "index.json").read_text(encoding="utf-8")
                check("index.json 已加密（非明文 JSON）",
                      "加密测试" not in raw and "entities" not in raw)
                # 重新加载可读回
                enc2 = HermesLite(root=enc_tmp)
                found = enc2._find(enc_id)
                check("加密存储读写一致", found is not None and "加密测试" in found["content"])
                check("主密钥文件 600 权限", oct((enc_tmp / ".master_key").stat().st_mode & 0o777) == "0o600")
            finally:
                del os.environ["HERMES_ENCRYPT"]
        finally:
            shutil.rmtree(enc_tmp, ignore_errors=True)

        print("\n" + "=" * 46)
        if FAILURES:
            print(f"❌ 测试失败 {len(FAILURES)} 项: {FAILURES}")
            return 1
        print("🎉 全部测试通过")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
