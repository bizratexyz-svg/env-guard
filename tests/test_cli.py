"""Unit tests for env-guard parsing, validation, secret scanning, and CLI."""

from __future__ import annotations

from pathlib import Path

import pytest

from env_guard.cli import (
    generate_example,
    infer_type,
    main,
    parse_env_file,
    scan_file_for_secrets,
    validate_value,
)


def test_parse_env_file_handles_comments_exports_and_types(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.example"
    env_file.write_text(
        "# @type: url\n"
        "API_ENDPOINT=https://api.example.com\n"
        'export QUOTED_VAL="hello world"\n'
        "PORT=8080 # inline comment\n",
        encoding="utf-8",
    )

    entries = parse_env_file(env_file)
    assert entries["API_ENDPOINT"].type_hint == "url"
    assert entries["API_ENDPOINT"].value == "https://api.example.com"
    assert entries["QUOTED_VAL"].value == "hello world"
    assert entries["PORT"].value == "8080"


def test_infer_and_validate_values() -> None:
    assert infer_type("DATABASE_URL", None) == "url"
    assert infer_type("SERVER_PORT", None) == "int"
    assert infer_type("DEBUG", None) == "bool"
    assert infer_type("ADMIN_EMAIL", None) == "email"

    assert validate_value("url", "https://example.com/api") is True
    assert validate_value("url", "not-a-url") is False
    assert validate_value("int", "8080") is True
    assert validate_value("int", "abc") is False
    assert validate_value("bool", "true") is True
    assert validate_value("bool", "maybe") is False
    assert validate_value("email", "dev@example.com") is True
    assert validate_value("email", "invalid-email") is False


def test_scan_file_for_secrets(tmp_path: Path) -> None:
    target = tmp_path / "config.env"
    target.write_text(
        "OPENAI_API_KEY=sk-proj-1234567890abcdefghij123456\n"
        "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n"
        "SAFE_KEY=changeme\n",
        encoding="utf-8",
    )

    findings = scan_file_for_secrets(target)
    rules = {f.rule for f in findings}
    assert "OpenAI / Stripe API key" in rules
    assert "AWS Access Key ID" in rules
    assert len(findings) == 2


def test_generate_example_strips_values(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    example_path = tmp_path / ".env.example"
    env_path.write_text(
        "# App settings\n"
        "API_KEY=super-secret\n"
        "export PORT=3000\n",
        encoding="utf-8",
    )

    rc = generate_example(env_path, example_path)
    assert rc == 0
    content = example_path.read_text(encoding="utf-8")
    assert "# App settings" in content
    assert "API_KEY=" in content
    assert "super-secret" not in content
    assert "export PORT=" in content


def test_cli_passing_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env_path = tmp_path / ".env"
    example_path = tmp_path / ".env.example"
    example_path.write_text("PORT=8080\nDEBUG=false\n", encoding="utf-8")
    env_path.write_text("PORT=3000\nDEBUG=true\n", encoding="utf-8")

    rc = main(["--env", str(env_path), "--example", str(example_path), "--no-color"])
    assert rc == 0
    assert "All checks passed!" in capsys.readouterr().out


def test_cli_detects_missing_extra_and_invalid_type(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env_path = tmp_path / ".env"
    example_path = tmp_path / ".env.example"
    example_path.write_text("PORT=8080\nREDIS_URL=redis://localhost:6379\n", encoding="utf-8")
    env_path.write_text("PORT=notanint\nEXTRA_VAR=1\n", encoding="utf-8")

    rc = main(["--env", str(env_path), "--example", str(example_path), "--no-color"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "REDIS_URL" in out
    assert "EXTRA_VAR" in out
    assert "expected int" in out


def test_cli_strict_mode_fails_on_warnings(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    example_path = tmp_path / ".env.example"
    example_path.write_text("APP_NAME=demo\n", encoding="utf-8")
    env_path.write_text("APP_NAME=demo\nEXTRA_ONLY=1\n", encoding="utf-8")

    assert main(["--env", str(env_path), "--example", str(example_path), "--no-color"]) == 0
    assert main(["--env", str(env_path), "--example", str(example_path), "--strict", "--no-color"]) == 1
