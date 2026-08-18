#!/usr/bin/env python3
"""Agent Memory 压力测试：150 条记忆规模下的性能验证。

使用 local 向量后端（不消耗 API 额度），验证：
  批量写入 → BM25/向量混合检索 → 图谱构建 → 淘汰预演 的耗时与正确性。
"""

import os
import random
import sys
import tempfile
import time
import shutil
from pathlib import Path

os.environ["HERMES_VECTOR_BACKEND"] = "local"
sys.path.insert(0, str(Path(__file__).parent))
from hermes_lite import HermesLite

N = 150
CATEGORIES = ["decision", "preference", "config", "project", "event"]
TECH = ["PostgreSQL", "Redis", "Kubernetes", "Docker", "Tavily", "Nginx",
        "Kafka", "Flink", "ClickHouse", "Milvus", "Prometheus", "Grafana"]
ACTIONS = ["决定采用", "选择", "配置了", "正在推进", "完成了", "偏好使用"]
TOPICS = ["作为缓存层", "作为消息队列", "用于监控告警", "作为向量数据库",
          "部署在测试环境", "用于日志采集", "作为 API 网关", "用于数据分析"]
EXTRA = ["用于订单系统", "用于用户服务", "用于库存管理", "用于支付网关",
         "用于推荐系统", "用于搜索服务", "用于数据同步", "用于权限控制"]


def main():
    tmp = Path(tempfile.mkdtemp(prefix="hermes_lite_stress_"))
    try:
        shutil.copy(Path(__file__).parent / "config.yaml", tmp / "config.yaml")
        mem = HermesLite(root=tmp)
        random.seed(42)

        # ---- 1. 批量写入（随机组合 + 唯一后缀，避免被去重合并） ----
        t0 = time.time()
        for i in range(N):
            content = (f"{random.choice(ACTIONS)} {random.choice(TECH)} "
                       f"{random.choice(TOPICS)}，{random.choice(EXTRA)}，"
                       f"标识 {''.join(random.choices('abcdefghijklmnopqrstuvwxyz', k=6))}")
            mem.remember(content,
                         category=random.choice(CATEGORIES),
                         importance=(i % 9) + 1,
                         verified=(i % 3 == 0))
        t_write = time.time() - t0

        # ---- 2. 混合检索（10 个查询） ----
        queries = ["PostgreSQL 缓存", "Redis 部署", "监控告警工具", "向量数据库选型",
                   "Kubernetes 环境", "消息队列方案", "日志采集系统", "API 网关",
                   "数据分析平台", "Prometheus 监控"]
        t0 = time.time()
        hit_counts = []
        for q in queries:
            hits = mem.recall(q, top_k=5)
            hit_counts.append(len(hits))
        t_recall = time.time() - t0

        # ---- 3. 图谱构建 ----
        t0 = time.time()
        mem.graph.build(mem.index)
        t_graph = time.time() - t0
        entity_count = len(mem.graph.data["entities"])

        # ---- 4. 淘汰预演 ----
        t0 = time.time()
        prune_result = mem.prune(dry_run=True)
        t_prune = time.time() - t0

        # ---- 5. 冷热/验证统计 ----
        stats = mem.stats()

        print("=" * 56)
        print(f"📈 压力测试：{N} 条记忆（local 向量后端）")
        print("=" * 56)
        print(f"写入 {N} 条:          {t_write*1000:.0f} ms（{t_write/N*1000:.1f} ms/条）")
        print(f"混合检索 10 个查询:   {t_recall*1000:.0f} ms（{t_recall/10*1000:.1f} ms/查询）")
        print(f"图谱构建:             {t_graph*1000:.0f} ms（{entity_count} 个实体）")
        print(f"淘汰预演:             {t_prune*1000:.0f} ms（过期 {prune_result['expired_count']} 条）")
        print(f"检索命中率:           {sum(1 for h in hit_counts if h)}/10 查询有结果")
        print(f"记忆分布:             {stats['total']} 条 | 热 {stats['hot']} | 冷 {stats['cold']} | "
              f"验证 {stats['verified']}")
        print(f"存储:                 index {stats['store_bytes']} 字节 + 向量缓存")
        print("=" * 56)

        # 正确性抽查：精确查询应命中对应记忆
        exact = mem.recall("PostgreSQL 作为缓存层", top_k=1)
        ok = bool(exact) and "PostgreSQL" in exact[0]["content"]
        print(f"精确检索抽查:         {'✅ 命中' if ok else '❌ 未命中'}")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
