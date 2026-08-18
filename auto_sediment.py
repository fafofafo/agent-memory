#!/usr/bin/env python3
"""自动沉淀：从 DSH 会话日志提取对话要点，经 digest 写入 Agent Memory 记忆库。

对话流接入约定：每次对话结束后运行本脚本，本轮的决策/偏好/配置/项目
要点自动沉淀入库（走完整链路：LLM 摘要 → 脱敏 → 去重 → 默认未验证）。

用法：
  python3 auto_sediment.py --dry-run           # 预览最新会话的沉淀要点（默认）
  python3 auto_sediment.py --apply             # 预览后写入记忆库
  python3 auto_sediment.py --apply --verified  # 写入并标记已验证
  python3 auto_sediment.py --file /path/session.jsonl   # 指定会话文件
  python3 auto_sediment.py --text "对话文本"            # 直接提供文本
  python3 auto_sediment.py --sessions-dir /path        # 会话日志目录（默认 ~/.dsh/sessions）
  python3 auto_sediment.py --max-chars 8000            # 输入 LLM 的文本上限
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from hermes_lite import HermesLite


def find_latest_session(sessions_dir: Path) -> Path | None:
    """在 DSH sessions 目录找最新的 session.jsonl(.zstd)。"""
    candidates = []
    if sessions_dir.exists():
        candidates = sorted(
            sessions_dir.rglob("session.jsonl*"),
            key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def extract_conversation(path: Path, sessions_dir: Path | None = None,
                         max_chars: int = 8000) -> str:
    """提取会话中的用户消息 + 助手文本（不含思考链/工具结果）。"""
    raw_text = ""
    if path.suffix == ".zstd":
        # 用 zstd 命令解压到 stdout
        result = subprocess.run(
            ["zstd", "-dc", str(path)], capture_output=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"zstd 解压失败: {result.stderr.decode()[:200]}")
        raw_text = result.stdout.decode("utf-8", errors="replace")
    else:
        raw_text = path.read_text(encoding="utf-8", errors="replace")

    parts = []
    for line in raw_text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        etype = event.get("type")
        data = event.get("data", {})
        if etype == "user/message":
            content = data.get("content", [])
            for c in content if isinstance(content, list) else []:
                if isinstance(c, dict) and c.get("type") == "text":
                    parts.append(f"用户: {c.get('text', '')}")
        elif etype == "assistant/message":
            msg = data.get("message", {})
            content = msg.get("content", [])
            for c in content if isinstance(content, list) else []:
                if isinstance(c, dict) and c.get("type") == "text":
                    parts.append(f"助手: {c.get('text', '')}")

    text = "\n".join(parts).strip()
    return text[:max_chars] if len(text) > max_chars else text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 DSH 会话自动沉淀记忆")
    parser.add_argument("--dry-run", action="store_true",
                        help="只预览不写入（默认）")
    parser.add_argument("--apply", action="store_true", help="预览后写入记忆库")
    parser.add_argument("--verified", action="store_true",
                        help="写入时标记已验证")
    parser.add_argument("--file", default=None, help="指定会话 jsonl 文件")
    parser.add_argument("--text", default=None, help="直接提供对话文本")
    parser.add_argument("--sessions-dir", default=None,
                        help="会话日志目录（默认 ~/.dsh/sessions）")
    parser.add_argument("--max-chars", type=int, default=8000)
    parser.add_argument("--root", default=None, help="Agent Memory 数据根目录")
    args = parser.parse_args(argv)

    # 1. 获取对话文本
    if args.text:
        text = args.text
        source = "直接文本"
    elif args.file:
        text = extract_conversation(Path(args.file), max_chars=args.max_chars)
        source = str(args.file)
    else:
        sessions_dir = Path(args.sessions_dir) if args.sessions_dir else (
            Path.home() / ".dsh" / "sessions")
        latest = find_latest_session(sessions_dir)
        if not latest:
            print("❌ 未找到会话日志（可指定 --sessions-dir 或 --file）")
            return 1
        text = extract_conversation(latest, max_chars=args.max_chars)
        source = str(latest)
    if not text.strip():
        print("❌ 会话文本为空")
        return 1

    # 2. 沉淀
    mem = HermesLite(root=args.root)
    result = mem.digest(text, apply=args.apply, max_facts=10,
                        verified=args.verified, source="对话流自动沉淀")

    mode_label = "LLM 摘要" if result["mode"] == "llm" else "规则式提取"
    print(f"🧠 对话来源: {source}")
    print(f"🧠 沉淀模式: {mode_label} | 提取 {len(result['facts'])} 条要点")
    for i, fact in enumerate(result["facts"], 1):
        cat_icon = {"preference": "⭐", "decision": "✅", "config": "⚙️",
                    "project": "📁", "event": "📅"}.get(fact.get("category"), "📌")
        print(f"  {i}. {cat_icon} [{fact.get('category', 'event')}] 重要{fact.get('importance', 5)}")
        print(f"     {fact['content']}")
    if args.apply:
        print(f"✅ 已写入 {len(result['applied'])} 条记忆（默认未验证，可 verify 确认）")
    else:
        print("💡 预览模式（未写入），加 --apply 写入记忆")
        print("   提示：确认无误后运行同命令加 --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
