---
title: "MCPサーバとシークレットはどこに置くべきか — STDIOとHTTPで変わる置き場所"
emoji: "🔐"
type: "tech"
topics: ["mcp","claude-code","secrets","ai-agents","security"]
published: false
---

MCPサーバを `claude_desktop_config.json` や `.mcp.json` にAPIキーを直書きして動いた経験はありませんか。動いた瞬間は便利ですが、そのキーは平文のままGitに乗り、ログに残り、エージェントのコンテキストウィンドウに入ります。

**結論はシンプルです。STDIO型は `env` に直書きしない。HTTP型はヘッダに直書きしない。どちらもbroker経由でプロセス層・トランスポート層で注入し、エージェントにはキーを見せないのが答えです。** この記事では、キーが物理的にどこに残るのかと、現実的な置き場所を整理します。

## キーはどこに残るのか

MCPサーバにキーを渡すと、最終的に3箇所に残ります。

- **クライアント設定ファイル**: Claude Desktopなら `claude_desktop_config.json`、CLIエージェントなら `.mcp.json` や `opencode.json`。`env` ブロックに平文で残ります。
- **サーバ側の `.env`**: サーバのインストール手順で「隣に `.env` を置いてください」と案内されるパターンです。
- **サーバプロセスの環境変数**: どの経路で渡しても、最終的にMCPサーバのプロセスが環境変数として保持します。ここが攻撃者から見た読み取り対象です。

設定ファイルは目に見えますが、実際に読まれるのはプロセスの環境変数です。ここを守れなければ、ファイルの置き場所を変えても意味がありません。

## STDIOとHTTPで何が違うのか

| 方式 | 設定例 | 残る場所 | 主なリスク |
|---|---|---|---|
| STDIO | `mcpServers.foo.env: { API_KEY: "sk-..." }` | `claude_desktop_config.json` / プロセスenv | dotfilesリポジトリへの混入、スクショ・共有での漏洩 |
| HTTP (Streamable) | `headers: { Authorization: "Bearer sk-..." }` | `mcp.json` / プロセスenv / 会話履歴 | ツール定義が会話に載る、プロキシログに残る |
| broker注入 | 設定ファイルにはキー名だけ | プロセスメモリ（一時的） | プロセスが読める範囲に限定できる |

STDIOはローカルプロセスとして起動されるため、設定ファイルの `env` がそのまま子プロセスの環境変数になります。HTTPはヘッダで運ばれるため、設定だけでなく通信経路でも触れる面が増えます。どちらも「ファイルに平文がある」時点で、Gitやバックアップ、画面共有で漏れます。

## 見落としがちな漏洩経路: ツール出力

MCPのツールはstdoutをクライアントに返し、その出力はモデルコンテキストに入ります。サーバが設定をそのままエコーしたり、エラー文にキーを含めたりすると、キーはコンテキストに載り、セッションログやプロバイダ側のリクエストログに残ります。悪意がなくても漏れる経路です。

```json
// やってしまいがちな例（STDIO）
{
  "mcpServers": {
    "my-server": {
      "command": "node",
      "args": ["server.js"],
      "env": { "GITHUB_TOKEN": "ghp_xxxxxxxxxxxx" }
    }
  }
}
```

```json
// やってしまいがちな例（HTTP）
{
  "mcpServers": {
    "remote-server": {
      "url": "https://mcp.example.com/mcp",
      "headers": { "Authorization": "Bearer sk-xxxxxxxx" }
    }
  }
}
```

どちらも「動く」ので、そのままコミットされがちです。

## 現実的な置き場所 — brokerで注入する

対策は「ファイルにキーを置かない」ことです。具体的には次の運用に倒します。

- **サーバごとにスコープを絞ったキーを1つずつ発行する**: 1つのキーを全サーバで使い回すと、1つのプロセスが侵害された時点で全てが漏れます。
- **broker経由で注入する**: trustlessなら `trustless mcp -- <server>` や `trustless run -s <key> -- <cmd>` で、ファイルには `GITHUB_TOKEN` という名前だけを置き、値はプロセス起動時にだけ環境変数として渡します。出力は `REDACTED` にマスクされ、送信時はDLPが再度マスクします。
- **設定ファイルはキー名だけを残す**: レビューで「値が平文で残っていないか」を機械的に検出できる状態にします。

```bash
# 例: STDIOサーバをbroker経由で起動（設定ファイルにキーは残らない）
trustless mcp -- npx -y my-mcp-server

# 例: HTTPヘッダはプロキシ層で注入（クライアント設定にBearerを書かない）
# trustless proxy のルールで header/query に注入
```

この形なら、エージェントは「`GITHUB_TOKEN` を使って」と名前で呼ぶだけで、平文を見ることはありません。キーはbrokerのプロセスメモリにだけ存在し、使った後は残りません。

## まとめ

MCPのキーは「設定ファイル → プロセス環境変数 → 会話履歴」の順に広がります。広がる前に、置き場所を1つ変えるだけで漏洩面は大きく減らせます。

あなたの `claude_desktop_config.json` や `.mcp.json` に、平文のキーは残っていませんか？まずは `grep -r "sk-\|ghp_\|Bearer"` で今の状態を確認してみてください。

---

> 元記事は trustless 公式サイトでも公開予定です: https://trustless-security.com/ja/blog/mcp-secrets-where-keys-live/

あなたの環境では、どのMCPサーバのキーを最初に見直しますか？
