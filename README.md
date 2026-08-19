# zenn-trustless

trustless の Zenn 記事リポジトリ。GitHub連携で `articles/*.md` を push → Zenn 自動公開。

## 運用（監修型・2-4本/月）

1. `python3 scripts/zenn-publish.py new --slug <slug> --title "..." --emoji "🔐" --type tech --topics "mcp,secrets,claude-code" --draft articles/<slug>.md`
   - `published: false` で draft 生成（相互リンク末尾に自動付与）
2. 本文執筆（600字以上・問題起点・冒頭100字で結論・末尾は問いかけで締める）
3. `python3 scripts/zenn-publish.py verify articles/*.md` で品質ゲート
4. レビュー後 `python3 scripts/zenn-publish.py publish articles/<slug>.md --at "2026-08-20 09:00"` → `published: true`
5. `git push` で Zenn に反映（予約公開は `published_at` の時刻で自動公開）

## Zenn側 設定

- Zennダッシュボード → GitHub連携 → このリポジトリ（`zenn-trustless`）の `main` を登録
- Publication `trustless` に紐付け推奨（未作成なら個人 `ikkun1222` でOK）

## 品質ゲート

- 本文600字以上 / 誇張語なし / 絵文字多用なし / 末尾は問いかけ / 相互リンクあり
- canonical は Zenn が正。本文末尾のリンクは `trustless-security.com/ja/blog/...` への導線。

## 文体

です・ます調で統一。
