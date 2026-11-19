# env-guard

[English](README.md) | **日本語**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

`.env` と `.env.example` の差分チェック、一般的な値のフォーマット検証、シークレット漏洩の検出、安全な `.env.example` テンプレート生成を行う、外部依存ゼロの Python CLI ツールです。

## 主な機能

- **Env 差分チェック**: `.env` と `.env.example` の間で不足しているキー、余分なキー、空の値を検出します。
- **シークレット検出**: `.env.example`（および `--scan-git` 指定時は `git` 追跡対象の全ファイル）をスキャンし、ハードコードされた API キーや秘密鍵（`sk-`, `ghp_`, `AKIA`, `xoxb-`, `AIza`, `sk-ant-`, PEM ヘッダー）を検出します。
- **フォーマット検証**: キー名からの推論、または `.env.example` 内の `# @type: <type>` コメントに基づいて、`url`、`int`、`bool`、`email` の形式を検証します。
- **安全なテンプレート生成**: コメントを保持したまま、シークレットの値をすべて除去したクリーンな `.env.example` を `.env` から生成します。
- **CI 対応**: 見やすいカラー表示のターミナル出力と、CI パイプライン向けの `--strict` モードを備えています。

## クイックスタート

Python 3.11 以上と [uv](https://docs.astral.sh/uv/) が必要です。

```bash
# uv で直接実行
uv run env-guard

# CI 向けの厳格モード（警告でも失敗させる）
uv run env-guard --strict --scan-git

# .env から安全に .env.example を生成
uv run env-guard --generate
```

## CLI オプション

| オプション | 説明 |
| :--- | :--- |
| `--env PATH` | `.env` ファイルのパス（デフォルト: `.env`） |
| `--example PATH` | `.env.example` ファイルのパス（デフォルト: `.env.example`） |
| `--generate` | 値を除去した `.env.example` を `.env` から安全に生成 |
| `--scan-git` | `git` 追跡対象の全ファイルからハードコードされたシークレットや API キーをスキャン |
| `--strict` | エラーだけでなく警告（余分なキー、空の値）でも非ゼロの終了コードで終了 |
| `--no-color` | ANSI カラー出力を無効化 |
| `--version` | バージョンを表示して終了 |

## `.env.example` での型アノテーション

`.env.example` 内にコメントを記述することで、期待される型を指定できます:

```dotenv
# @type: url
API_ENDPOINT=https://api.example.com

# @type: int
PORT=8080

# @type: bool
DEBUG=false

# @type: email
ADMIN_EMAIL=admin@example.com
```

## 出力例

```text
$ uv run env-guard --strict
env-guard report
────────────────────────────────────────

✗ Missing keys (in .env.example but not .env):
  - REDIS_URL

! Extra keys (in .env but not .env.example):
  - LOCAL_DEBUG_FLAG

✗ Format validation errors (in .env):
  - PORT (line 4): expected int, got 'abc'

✗ Potential hardcoded secrets detected:
  - .env.example:7 [OpenAI / Stripe API key] (sk-pro...9xQz)

✗ Errors: 3 | Warnings: 1
```

## ライセンス

MIT
