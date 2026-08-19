#!/usr/bin/env python3
"""zenn-publish — Zenn記事の draft 生成・品質ゲート・publish 変換。

品質方針（trustless/agentjournal 共通の監修型）:
- 量産しない。Fact Sheet + 技術検証 + 人間レビューの 2-4本/月ペース。
- 本スクリプトは frontmatter 変換と品質ゲートを担う。執筆自体は人間 or LLM の draft 生成後に本スクリプトで検証する。
- Zenn は public リポジトリの articles/*.md を push で自動公開。published:false -> レビュー -> true。

使い方:
  python3 scripts/zenn-publish.py new --slug my-article --title "..." --emoji "🔐" --type tech --topics "a,b" --draft articles/my-article.md
    # articles/<slug>.md を published:false で作成（末尾に相互リンク付与）
  python3 scripts/zenn-publish.py verify articles/*.md
    # 品質ゲート: 文字数・誇張語・絵文字重複・末尾の問い・canonical リンク等
  python3 scripts/zenn-publish.py publish articles/my-article.md --at "2026-08-20 09:00"
    # published:true + published_at を付与（予約公開）

Zenn frontmatter 仕様: https://zenn.dev/zenn/articles/zenn-cli-guide
  title, emoji(1つ), type(tech/idea), topics(最大5), published, published_at(YYYY-MM-DD [hh:mm])
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from datetime import datetime

SITE_TRUSTLESS = "https://trustless-security.com/ja/blog"
SITE_AGENTJOURNAL = "https://agentjournal.dev/articles"

HYPE = ["revolutionary", "game-changing", "best-ever", "cutting-edge", "groundbreaking", "state-of-the-art",
        "革命的", "業界初", "世界初", "最強"]
# Zenn本文では末尾に相互リンクを入れる想定。Hugoのcanonicalは <link rel="canonical"> で別途担保。
EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\U0001F1E6-\U0001F1FF]")

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def cmd_new(args) -> None:
    out = Path(args.draft) if args.draft else Path(f"articles/{args.slug}.md")
    if out.exists():
        print(f"already exists: {out}", file=sys.stderr)
        sys.exit(1)
    topics = [t.strip() for t in (args.topics or "").split(",") if t.strip()][:5]
    topics_str = "[" + ",".join(f'"{t}"' for t in topics) + "]" if topics else "[]"
    # 相互リンク先は repo 名から推定
    repo = Path.cwd().name  # zenn-trustless / zenn-agentjournal
    if "trustless" in repo:
        footer = f"\n\n---\n\n> 元記事は trustless 公式サイトでも公開予定です: {SITE_TRUSTLESS}/{args.slug}/"
    else:
        footer = f"\n\n---\n\n> 元記事: {SITE_AGENTJOURNAL}/{args.slug}/ — 英語版の深掘りも公開予定です。"
    body = f"""ここに本文を書きます。600-1000字を目安に、問題起点 → 結論を冒頭100字で → 事実ベース → 末尾は問いかけで締めてください。\n\n## はじめに\n\n課題: ...（なぜこの記事を書くのか）\n\n## 結論\n\n...（冒頭100字で答えを出す）\n\n## 事実と検証\n\n...（コマンド・ログ・実測を添える）\n\n## まとめ\n\n...？\n"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f'---\ntitle: "{args.title}"\nemoji: "{args.emoji}"\ntype: "{args.type}"\ntopics: {topics_str}\npublished: false\n---\n\n' + body + footer + "\n",
        encoding="utf-8",
    )
    print(f"created {out} (published:false — レビュー後に publish --at で予約)")

def check_one(path: Path) -> list[str]:
    text = _read(path)
    problems: list[str] = []
    # frontmatter 抽出
    if not text.startswith("---"):
        problems.append("frontmatter が --- で始まっていない")
        return problems
    try:
        _, fm, body = text.split("---", 2)
    except ValueError:
        problems.append("frontmatter の --- 区切りが不正")
        return problems
    # published は verify 時は false でもOK（gate は内容）
    # 文字数は body の日本語文字数で 600-1500 字程度を目安（Zenn は Hugo の600-700words とは別基準）
    body_stripped = body.strip()
    # 日本語文字数（空白除去後の文字数で概算）
    ja_chars = len(re.sub(r"\s+", "", body_stripped))
    if ja_chars < 600:
        problems.append(f"本文が短い: 約{ja_chars}字 (目安600字以上)")
    if ja_chars > 4000:
        problems.append(f"本文が長すぎる: 約{ja_chars}字 (目安4000字以内に分割推奨)")
    low = body.lower()
    hits = [h for h in HYPE if h.lower() in low or h in body]
    if hits:
        problems.append(f"誇張語: {hits}")
    # emoji は frontmatter の1つ以外は本文に多用しない
    emoji_hits = EMOJI_RE.findall(body)
    if len(emoji_hits) > 5:
        problems.append(f"本文の絵文字が多い: {len(emoji_hits)}件")
    if not body_stripped.rstrip().endswith(("?", "？")):
        problems.append("本文末尾が問いかけ（? / ？）で終わっていない")
    # 相互リンクの存在チェック（推奨）
    if "trustless-security.com" not in body and "agentjournal.dev" not in body and len(body_stripped) > 500:
        problems.append("末尾の相互リンク（trustless-security.com / agentjournal.dev）が未挿入")
    # slug とファイル名の一致は new 経由なら担保されるが、verify でも軽く見る
    return problems

def cmd_verify(args) -> None:
    files = [Path(p) for p in args.files]
    if not files:
        print("usage: zenn-publish verify <articles/*.md>", file=sys.stderr)
        sys.exit(2)
    failed = False
    for f in files:
        if not f.exists():
            print(f"SKIP {f} (not found)")
            continue
        probs = check_one(f)
        status = "OK  " if not probs else "FAIL"
        print(f"{status} {f}" + (f"  -> {probs}" if probs else ""))
        failed = failed or bool(probs)
    sys.exit(1 if failed else 0)

def cmd_publish(args) -> None:
    path = Path(args.file)
    text = _read(path)
    if not text.startswith("---"):
        print("frontmatter が見つからない", file=sys.stderr)
        sys.exit(1)
    # published: false -> true
    if "published: false" in text:
        text = text.replace("published: false", "published: true", 1)
    elif "published: true" in text:
        pass
    else:
        # published 行が無ければ追加
        text = text.replace("---\n", "---\n", 1)  # no-op to keep structure
        # 挿入: topics の次行に published
        text = re.sub(r"(topics:.*\n)", r"\1published: true\n", text, count=1)
    # published_at
    if args.at:
        # YYYY-MM-DD [hh:mm] 形式を検証
        try:
            # 2形式を許容
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    datetime.strptime(args.at, fmt)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError
        except ValueError:
            print("published_at は YYYY-MM-DD または YYYY-MM-DD hh:mm で", file=sys.stderr)
            sys.exit(1)
        if "published_at:" in text:
            text = re.sub(r"published_at:.*\n", f"published_at: {args.at}\n", text)
        else:
            text = text.replace("published: true", f"published: true\npublished_at: {args.at}", 1)
    path.write_text(text, encoding="utf-8")
    print(f"published {path} (published:true{' at ' + args.at if args.at else ''} — push でZennに反映)")

def main() -> None:
    ap = argparse.ArgumentParser(description="Zenn publish helper")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new")
    p.add_argument("--slug", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--emoji", default="📝")
    p.add_argument("--type", choices=["tech", "idea"], default="tech")
    p.add_argument("--topics", default="")
    p.add_argument("--draft", default=None, help="出力パス (default: articles/<slug>.md)")
    p = sub.add_parser("verify")
    p.add_argument("files", nargs="+")
    p = sub.add_parser("publish")
    p.add_argument("file")
    p.add_argument("--at", default=None, help="published_at YYYY-MM-DD [hh:mm]")
    args = ap.parse_args()
    if args.cmd == "new":
        cmd_new(args)
    elif args.cmd == "verify":
        cmd_verify(args)
    elif args.cmd == "publish":
        cmd_publish(args)

if __name__ == "__main__":
    main()
