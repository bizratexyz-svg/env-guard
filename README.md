# env-guard

**English** | [日本語](README.ja.md)

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A zero-dependency Python CLI tool to diff `.env` against `.env.example`, validate common value formats, detect leaked secrets, and safely generate `.env.example` templates.

## Features

- **Env Diffing**: Detects missing keys, extra keys, and empty values between `.env` and `.env.example`.
- **Secret Detection**: Scans `.env.example` (and optionally all `git`-tracked files with `--scan-git`) for hardcoded API keys and private keys (`sk-`, `ghp_`, `AKIA`, `xoxb-`, `AIza`, `sk-ant-`, PEM headers).
- **Format Validation**: Validates `url`, `int`, `bool`, and `email` values via key-name inference or `# @type: <type>` comments in `.env.example`.
- **Safe Template Generation**: Generate a clean `.env.example` from `.env` with all secret values stripped while preserving comments.
- **CI-Ready**: Clean colored terminal output and `--strict` mode for CI pipelines.

## Quick Start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
# Run directly with uv
uv run env-guard

# Strict mode for CI (fails on warnings too)
uv run env-guard --strict --scan-git

# Generate .env.example safely from .env
uv run env-guard --generate
```

## CLI Options

| Option | Description |
| :--- | :--- |
| `--env PATH` | Path to the `.env` file (default: `.env`) |
| `--example PATH` | Path to the `.env.example` file (default: `.env.example`) |
| `--generate` | Generate `.env.example` safely from `.env` with values stripped |
| `--scan-git` | Scan all `git`-tracked files for hardcoded secrets/API keys |
| `--strict` | Exit non-zero on warnings (extra keys, empty values) as well as errors |
| `--no-color` | Disable ANSI colored output |
| `--version` | Show version and exit |

## Type Annotations in `.env.example`

You can annotate expected types with comments in `.env.example`:

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

## Example Output

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

## License

MIT
