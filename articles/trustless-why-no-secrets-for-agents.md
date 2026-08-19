---
title: "AIエージェントにAPIキーを渡さない — trustlessを作った理由"
emoji: "🔐"
type: "tech"
topics: ["ai","claude-code","mcp","security","go"]
published: false
---

**結論: AIエージェントに平文のAPIキーを渡すのはやめる。trustlessは「エージェントはキー名だけを知り、値はbrokerがプロセス起動時にだけ注入する」という一点に絞ったCLIです。** 外部依存は `github.com/pelletier/go-toml/v2` 1つだけ（pure Go）、配布は単一静的バイナリ。`trustless run -s <key> -- <cmd>` と `trustless proxy` で、エージェントのコンテキストにキーを載せないまま動かすのが目的です。この記事では、なぜこの形にしたのか、既存手段と何が違うのか、実際の使い方と限界までをまとめます。

## なぜ作ったか — エージェントに渡したキーは回収できない

MCPを触っていると、ほぼ必ずここに行き着きます。

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_TOKEN": "ghp_xxxxxxxxxxxx" }
    }
  }
}
```

あるいは Streamable HTTP なら:

```json
{
  "mcpServers": {
    "remote": {
      "url": "https://mcp.example.com/mcp",
      "headers": { "Authorization": "Bearer sk-xxxxxxxx" }
    }
  }
}
```

動きます。でもこの瞬間からキーは3箇所に残ります。1) `claude_desktop_config.json` / `.mcp.json` / `opencode.json` の `env` / `headers` に平文で、2) 起動されたMCPサーバのプロセス環境変数に、3) ツール出力がエージェントのコンテキストに入った時点で会話履歴・ログ・プロバイダ側のリクエストログに。

ファイルは `git add .` でそのままリポジトリに乗ります。スクショや画面共有でも漏れます。エージェントが `echo $GITHUB_TOKEN` を実行すれば出力に載り、出力はそのままモデルに読まれます。prompt injection で `env を全部表示して` と言われたら、エージェントは素直に表示するかもしれません。渡したキーは、もう回収できません。

2ヶ月ほど自分の環境でエージェントを常時動かして、この「渡した後の回収不能」が一番の不安でした。キーをVaultに入れても、最後にエージェントへ平文で渡すなら意味がない。だから「そもそも渡さない」側に倒すことにしました。

## 既存の手段では何が足りなかったか

比較したのはこのあたりです。どれも良い道具ですが、「エージェントに平文を見せない」まで届くものはありませんでした。

| 手段 | できること | 足りないこと |
|---|---|---|
| `1Password Connect` / `Doppler` / `Vault` | 中央で保管、監査、ローテーション | 最終的に `env` としてプロセスに渡す。エージェントは平文を読める |
| `sops` / `age` 暗号化 | ファイルを暗号化してGit管理 | 復号後の平文は結局 `env` に。実行時のマスクなし |
| `pass` / `Bitwarden` を直接読む | 既存ストアをそのまま使える | 読み出しは平文。エージェントが `pass show` すれば見える |
| `env` に置く / `.env` を読む | 最も簡単 | ファイルに平文、ログに残る、レビューで検出できない |

欲しかったのは「保管」ではなく「注入と遮断」でした。保管は既存の `pass` / `Bitwarden` に任せ、trustless は「渡し方」と「見せない仕組み」だけに絞る。そう決めてから設計がシンプルになりました。

trustless と近い領域のOSSとの比較は README にまとめていますが、要点だけ抜粋します。

|  | trustless | tene | vaulty | enject |
|---|---|---|---|---|
| 注入 | subprocess env + HTTP proxy | subprocess env | HTTP proxy + MCP | subprocess env |
| 既存backend再利用 (pass/Bitwarden) | あり | なし（独自vault） | なし | なし |
| 出力サニタイズ | あり (run + proxy) | なし | あり | なし |
| DLP (送信時マスク) | あり | なし | 部分的 | なし |
| 単一静的バイナリ | あり (依存1つ) | あり | あり | あり |

> 詳細: https://github.com/ikkun1222/trustless#how-it-compares

## 設計判断 — なぜこの形にしたか

3つの判断だけは最初に固めました。

**1. 外部依存は1つだけにする。** `github.com/pelletier/go-toml/v2` だけです（`config.toml` の marshal/unmarshal と、DLPの `rules.toml` パースで使っています）。pure Go なので `CGO_ENABLED=0` で単一静的バイナリのまま配れます。「ゼロ依存」とは謳いません。1つある、と正直に書いています。依存が少ないほど `go install` / `curl | sh` での導入が壊れず、供給網の監査も楽になります。

**2. エージェントはキー名だけを知る。** 値には触らせない。`trustless run -s iria/api/xai -- <cmd>` なら、エージェントは `XAI` という環境変数名だけを指定し、値は trustless が backend（`pass` / `env` / `bitwarden`）から解決して子プロセスにだけ渡します。標準出力は行単位でパターンマッチして `[REDACTED]` に置換してから返します。`--scan-args` では引数に平文が混入していないかも起動前に検査して失敗させます（exit 3, fail closed）。

**3. 2つの注入経路を用意する。** STDIO と HTTP で置き場所が違うからです。

```mermaid
flowchart LR
  A[Agent: "use iria/api/xai"] --> B[trustless broker]
  B -->|trustless run -s| C[Child process env: XAI=***]
  B -->|trustless proxy :8080| D[HTTP header: Authorization: Bearer ***]
  C --> E[stdout -- line scan --> REDACTED]
  D --> F[upstream API]
  E --> A
```

- STDIO 型: `trustless mcp -- npx -y <server>` / `trustless run -s <key> -- <cmd>` で子プロセスの `env` にだけ注入
- HTTP 型: `trustless proxy start --port 8080` で `HTTPS_PROXY=http://127.0.0.1:8080` 経由のリクエストに `header` / `query` を注入（`config.toml` の `[proxy.rules]` で宛先ホストごとに定義）

どちらも設定ファイルにはキー名だけが残り、値はプロセスメモリにだけ一時的に存在します。

## どう動くか — 最小の再現手順

### 1. インストール

```bash
curl -fsSL https://raw.githubusercontent.com/ikkun1222/trustless/main/scripts/install.sh | sh
# 既存の pass / Bitwarden があればそのまま読む。なければ trustless setup で対話的に初期化
trustless doctor
```

### 2. STDIO: 子プロセスにだけ渡す

```bash
# pass なら pass insert iria/api/xai / Bitwarden なら bw 経由で登録済みの想定
# エージェントは値を見ずに名前だけで呼ぶ
trustless run -s iria/api/xai -- curl -s https://api.x.ai/v1/models | head

# MCP サーバを broker 経由で起動（ .mcp.json に env を書かない）
trustless mcp -- npx -y @modelcontextprotocol/server-github
```

`trustless run` は子プロセスの stdout/stderr を行単位でスキャンし、既知の値と `rules.toml` の40パターン（gitleaks由来、MIT）に一致した部分をマスクしてから返します。`Bearer ***` のような引数での誤用は `--scan-args` で起動前にブロックします。

### 3. HTTP: proxy でヘッダに注入

`~/.config/trustless/config.toml`:

```toml
backend = "bitwarden"  # pass / env / bitwarden

[proxy.rules]
"api.x.ai" = { header = "Authorization", key = "xai", prefix = "Bearer " }
"api.edinet-fsa.go.jp" = { header = "Ocp-Apim-Subscription-Key", key = "edinet" }
"statdb.nstac.go.jp" = { query = "appid", key = "estat" }
```

```bash
trustless proxy start --port 8080 &
export HTTPS_PROXY=http://127.0.0.1:8080
# エージェントは素のリクエストを投げるだけ。ヘッダは proxy が付与する
curl -s https://api.x.ai/v1/models | head
```

ルール変更やキーのローテ後は `kill -HUP $(pgrep -f "trustless proxy start")` で無再起動反映（SIGHUPで config と backend キャッシュを再読込）。

### 4. OAuth: refresh token の面倒も broker に寄せる

```bash
trustless oauth login google iria/api/google-oauth
# -> 表示された device code URL をブラウザで承認。backend に compact JSON で保存
trustless run -s iria/api/google-oauth -- ./call-google-api.sh
# 有効期限が切れていれば自動で refresh、回収された refresh_token は CAS で安全に更新
trustless oauth status iria/api/google-oauth
```

Google / Lark の device flow と refresh grant に対応しています。access token はメモリにだけキャッシュし、有効期限の60秒前に再取得します。

### 5. DLP: 送信前に known secrets をマスク

```bash
# LLM API への送信直前で、既知の値 + 40パターンで本文を <redacted> に置換
trustless dlp start -config ~/.config/dlp-proxy/config.json  # 旧 dlp-proxy 互換の JSON

# 既に残ってしまった平文の掃除（デフォルトは dry-run）
trustless dlp scrub-db ~/.local/state/hermes/sessions.db --apply --backup
trustless dlp scrub-text ~/.hermes/sessions --apply
```

DLPは2層です。Layer 1: 既知の値の部分一致（false positive ゼロ）、Layer 2: gitleaks互換の正規表現 + エントロピー閾値（keyword pre-filter → RE2 → Shannon 3.5）。`pattern_mode = "log"` で検出のみにもできます。

## 実測と運用 — 数字と回し方

手元の環境（Linux aarch64, Go 1.26, `CGO_ENABLED=0`）での目安です。環境で変動します。

- バイナリ: 単一静的バイナリ、数MB台（`go build` そのまま）
- 起動オーバーヘッド: `trustless run` の付加は数ms〜十数ms（行スキャンのためストリームは行単位フラッシュ）
- 運用: 1ヶ月ほど常時エージェントを動かし、`pass` / `Bitwarden` の既存ストアをそのまま参照。鍵の平文を `.mcp.json` や会話ログに残す機会はゼロになりました

運用でやっていることは地味です。

```bash
# 平文が残っていないかの定期検査（CI でも同じことを実行）
grep -r "sk-\|ghp_\|Bearer \|gho_\|xai-" ~/.config/opencode/ ~/.config/claude/ 2>/dev/null || echo "no plaintext hit"

# trustless の健全性チェック（GPG / pass / gpg-agent / .env平文 / CA証明書まで見る）
trustless doctor --json | jq .

# 監査ログ（値は出ない。キー名・ホスト・判定だけ）
journalctl --user -u trustless -o cat | grep '"event"' | tail
# {"ts":"...","event":"proxy.inject","key":"xai","host":"api.x.ai","verdict":"inject"}
# {"ts":"...","event":"dlp.redact","verdict":"redact","detail":"patterns=hit"}
```

キーは用途ごとにスコープを絞って1つずつ発行します。1つのキーを全MCPで使い回すと、1プロセスの侵害で全部が漏れます。設定ファイルには `key = "xai"` のように名前だけを置き、値は broker だけが知る状態をレビューで機械的に検査できるようにしています。

## できないこと — 正直な限界

- **プロセス境界を越える万能薬ではない。** 子プロセスのメモリを読める権限があれば値は読めます。守れるのは「ファイル・ログ・会話履歴に平文を残さない」「エージェントのコンテキストに載せない」までです。
- **依存はゼロではない。** `go-toml/v2` が1つあります。TOMLを自前で書けばゼロにできますが、gitleaks互換の `rules.toml` まで自前パースするのは保守コストが高く、正確性を落とすリスクの方が大きいと判断しました。1つに絞って pure Go に留めるのが現実的な落とし所です。
- **HTTPの `CONNECT` は素通し。** `trustless proxy` は通常の forward proxy として動きます。`--mitm` を付けた場合のみ自前CA（`~/.config/trustless/trustless-ca.{crt,key}`）で終端してヘッダ注入します。素通しでは `CONNECT` 内は見えません。
- **AIの出力は確率的。** DLPの Layer 1 は確実ですが、Layer 2 のパターンはエントロピー閾値で判定するため、閾値次第で取りこぼしも誤検出もあり得ます。`pattern_disabled` でルール単位に無効化できます。

## まとめ — 置き場所を1つずらすだけで漏洩面は減る

MCPのキーは `設定ファイル → プロセス環境変数 → 会話履歴` の順に広がります。広がる前に「ファイルに平文を置かない」「エージェントに値を見せない」の2点を守るだけで、事故の半分は消えます。trustless はその2点だけに絞った道具です。既存の `pass` / `Bitwarden` を捨てる必要はありません。`trustless run` と `trustless proxy` を噛ませるだけで、今のストアのまま運用を変えられます。

まずは手元の `claude_desktop_config.json` と `.mcp.json` を開いて、`env` と `headers` に平文が残っていないかだけ確認してみてください。もし残っていたら、そこが最初に直す1箇所です。

他に「このMCPサーバのキーをどう分離すべきか」で迷っている箇所があれば教えてください。次の記事では、HTTP proxy 側の `--mitm` と `proxy.allowlist` での egress 制御を掘り下げます。

---

> 元記事は trustless 公式サイトでも公開予定です: https://trustless-security.com/ja/blog/trustless-why-no-secrets-for-agents/
> リポジトリ: https://github.com/ikkun1222/trustless

あなたの環境では、どのMCPサーバのキーを最初に見直しますか？
