"""CLI entry point and core logic for env-guard."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from env_guard import __version__


# ---------------------------------------------------------------------------
# Terminal color helpers
# ---------------------------------------------------------------------------

class Colors:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        if not self.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def red(self, text: str) -> str:
        return self._wrap("31", text)

    def green(self, text: str) -> str:
        return self._wrap("32", text)

    def yellow(self, text: str) -> str:
        return self._wrap("33", text)

    def cyan(self, text: str) -> str:
        return self._wrap("36", text)


# ---------------------------------------------------------------------------
# Secret detection patterns
# ---------------------------------------------------------------------------

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("OpenAI / Stripe API key", re.compile(r"\bsk-(?:proj-|live-|test-)?[A-Za-z0-9_-]{20,}\b")),
    ("GitHub Personal Access Token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("AWS Access Key ID", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack Token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("Google API Key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Anthropic API Key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("Private Key Header", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
]

PLACEHOLDER_VALUES = {
    "",
    "changeme",
    "change_me",
    "your_api_key",
    "your-api-key",
    "your_secret",
    "your-secret",
    "xxx",
    "xxxx",
    "todo",
    "replace_me",
    "example",
}


# ---------------------------------------------------------------------------
# Data structures & .env parsing
# ---------------------------------------------------------------------------

@dataclass
class EnvEntry:
    key: str
    value: str
    line_no: int
    type_hint: str | None = None


@dataclass
class SecretFinding:
    path: Path
    line_no: int
    rule: str
    snippet: str


@dataclass
class ValidationIssue:
    key: str
    expected_type: str
    value: str
    line_no: int


@dataclass
class GuardReport:
    missing_keys: list[str] = field(default_factory=list)
    extra_keys: list[str] = field(default_factory=list)
    empty_keys: list[str] = field(default_factory=list)
    type_issues: list[ValidationIssue] = field(default_factory=list)
    secret_findings: list[SecretFinding] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len(self.missing_keys) + len(self.secret_findings) + len(self.type_issues)

    @property
    def warning_count(self) -> int:
        return len(self.extra_keys) + len(self.empty_keys)


TYPE_ANNOTATION_RE = re.compile(r"#\s*@?type\s*:\s*(url|int|bool|email)\b", re.IGNORECASE)
ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _strip_quotes(raw: str) -> str:
    val = raw.strip()
    if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
        return val[1:-1]
    # Strip inline comment for unquoted values
    if " #" in val:
        val = val.split(" #", 1)[0].strip()
    return val


def parse_env_file(path: Path) -> dict[str, EnvEntry]:
    """Parse a .env or .env.example file into an ordered dict of EnvEntry."""
    entries: dict[str, EnvEntry] = {}
    pending_type: str | None = None

    for idx, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            pending_type = None
            continue
        if stripped.startswith("#"):
            m_type = TYPE_ANNOTATION_RE.search(stripped)
            if m_type:
                pending_type = m_type.group(1).lower()
            continue

        m = ENV_LINE_RE.match(line)
        if not m:
            pending_type = None
            continue

        key = m.group(1)
        raw_val = m.group(2)

        inline_type: str | None = None
        m_inline = TYPE_ANNOTATION_RE.search(raw_val)
        if m_inline:
            inline_type = m_inline.group(1).lower()

        val = _strip_quotes(raw_val)
        entries[key] = EnvEntry(
            key=key,
            value=val,
            line_no=idx,
            type_hint=inline_type or pending_type,
        )
        pending_type = None

    return entries


# ---------------------------------------------------------------------------
# Value format inference & validation
# ---------------------------------------------------------------------------

def infer_type(key: str, example_entry: EnvEntry | None) -> str | None:
    """Determine expected value type from explicit annotation, example value, or key name."""
    if example_entry and example_entry.type_hint:
        return example_entry.type_hint

    upper = key.upper()
    if upper.endswith(("_URL", "_URI", "_ENDPOINT")) or upper in {"URL", "BASE_URL", "DATABASE_URL", "REDIS_URL"}:
        return "url"
    if upper.endswith(("_PORT", "_TIMEOUT", "_SECONDS", "_MS", "_COUNT", "_LIMIT")) or upper in {"PORT"}:
        return "int"
    if upper.endswith(("_ENABLED", "_ENABLE", "_ACTIVE")) or upper in {"DEBUG", "VERBOSE", "DRY_RUN"}:
        return "bool"
    if upper.endswith("_EMAIL") or upper in {"EMAIL", "ADMIN_EMAIL", "FROM_EMAIL"}:
        return "email"

    if example_entry and example_entry.value:
        v = example_entry.value.strip()
        if v.lower() in {"true", "false"}:
            return "bool"
        if v.startswith(("http://", "https://")):
            return "url"
        if EMAIL_RE.match(v):
            return "email"

    return None


def validate_value(expected_type: str, value: str) -> bool:
    """Validate a non-empty value against url, int, bool, or email."""
    v = value.strip()
    if not v:
        return True
    if expected_type == "int":
        return bool(re.fullmatch(r"-?\d+", v))
    if expected_type == "bool":
        return v.lower() in {"true", "false", "1", "0", "yes", "no", "on", "off"}
    if expected_type == "email":
        return bool(EMAIL_RE.match(v))
    if expected_type == "url":
        parsed = urlparse(v)
        return bool(parsed.scheme and parsed.netloc)
    return True


# ---------------------------------------------------------------------------
# Secret scanning
# ---------------------------------------------------------------------------

def _redact(snippet: str) -> str:
    if len(snippet) <= 12:
        return snippet[:4] + "..."
    return snippet[:6] + "..." + snippet[-4:]


def scan_file_for_secrets(path: Path) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    try:
        # Skip large files (>1 MB) and binary files
        if not path.is_file() or path.stat().st_size > 1_000_000:
            return findings
        raw = path.read_bytes()
        if b"\x00" in raw[:4096]:
            return findings
        text = raw.decode("utf-8", errors="replace")
    except OSError:
        return findings

    for idx, line in enumerate(text.splitlines(), start=1):
        for rule_name, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(line):
                token = match.group(0)
                if token.lower() in PLACEHOLDER_VALUES:
                    continue
                findings.append(
                    SecretFinding(
                        path=path,
                        line_no=idx,
                        rule=rule_name,
                        snippet=_redact(token),
                    )
                )
    return findings


def list_git_tracked_files(cwd: Path) -> list[Path]:
    try:
        proc = subprocess.run(
            ["git", "ls-files"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return []
        return [cwd / p for p in proc.stdout.splitlines() if p.strip()]
    except FileNotFoundError:
        return []


# ---------------------------------------------------------------------------
# Template generation
# ---------------------------------------------------------------------------

def generate_example(env_path: Path, example_path: Path) -> int:
    """Create .env.example from .env with values stripped, preserving comments."""
    if not env_path.exists():
        print(f"Error: {env_path} does not exist.", file=sys.stderr)
        return 1

    out_lines: list[str] = []
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = ENV_LINE_RE.match(line)
        if m:
            key = m.group(1)
            prefix = "export " if line.lstrip().startswith("export ") else ""
            out_lines.append(f"{prefix}{key}=")
        else:
            out_lines.append(line)

    example_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="env-guard",
        description="Diff .env against .env.example, validate value formats, and detect hardcoded secrets.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--env",
        type=Path,
        default=Path(".env"),
        help="Path to the .env file (default: .env)",
    )
    parser.add_argument(
        "--example",
        type=Path,
        default=Path(".env.example"),
        help="Path to the .env.example file (default: .env.example)",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate .env.example safely from .env with all values stripped.",
    )
    parser.add_argument(
        "--scan-git",
        action="store_true",
        help="Also scan all git-tracked files for hardcoded secrets/API keys.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with non-zero status on warnings (extra keys, empty values) as well as errors.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colored output.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    use_color = not args.no_color and "NO_COLOR" not in os.environ and sys.stdout.isatty()
    c = Colors(use_color)

    if args.generate:
        rc = generate_example(args.env, args.example)
        if rc == 0:
            print(f"{c.green('✓')} Generated {c.bold(str(args.example))} safely from {c.bold(str(args.env))}.")
        return rc

    report = GuardReport()

    env_exists = args.env.exists()
    example_exists = args.example.exists()

    env_entries = parse_env_file(args.env) if env_exists else {}
    example_entries = parse_env_file(args.example) if example_exists else {}

    if not env_exists and not example_exists and not args.scan_git:
        print(f"{c.red('✗')} Neither {args.env} nor {args.example} was found.", file=sys.stderr)
        return 1

    if env_exists and example_exists:
        for key in example_entries:
            if key not in env_entries:
                report.missing_keys.append(key)
        for key in env_entries:
            if key not in example_entries:
                report.extra_keys.append(key)

    if env_exists:
        for key, entry in env_entries.items():
            if entry.value == "":
                report.empty_keys.append(key)
            else:
                expected = infer_type(key, example_entries.get(key))
                if expected and not validate_value(expected, entry.value):
                    report.type_issues.append(
                        ValidationIssue(
                            key=key,
                            expected_type=expected,
                            value=entry.value,
                            line_no=entry.line_no,
                        )
                    )

    # Scan .env.example for accidentally committed secrets
    if example_exists:
        report.secret_findings.extend(scan_file_for_secrets(args.example))

    # Optionally scan git-tracked files
    if args.scan_git:
        seen = {args.example.resolve()} if example_exists else set()
        for tracked in list_git_tracked_files(Path.cwd()):
            resolved = tracked.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            report.secret_findings.extend(scan_file_for_secrets(tracked))

    # Render report
    print(c.bold("env-guard report"))
    print(c.dim("─" * 40))

    if report.missing_keys:
        print(f"\n{c.red('✗ Missing keys')} (in {args.example} but not {args.env}):")
        for key in report.missing_keys:
            print(f"  - {c.bold(key)}")

    if report.extra_keys:
        print(f"\n{c.yellow('! Extra keys')} (in {args.env} but not {args.example}):")
        for key in report.extra_keys:
            print(f"  - {key}")

    if report.empty_keys:
        print(f"\n{c.yellow('! Empty values')} (in {args.env}):")
        for key in report.empty_keys:
            print(f"  - {key}")

    if report.type_issues:
        print(f"\n{c.red('✗ Format validation errors')} (in {args.env}):")
        for issue in report.type_issues:
            print(
                f"  - {c.bold(issue.key)} (line {issue.line_no}): "
                f"expected {c.cyan(issue.expected_type)}, got {issue.value!r}"
            )

    if report.secret_findings:
        print(f"\n{c.red('✗ Potential hardcoded secrets detected')}:")
        for f in report.secret_findings:
            print(f"  - {c.bold(str(f.path))}:{f.line_no} [{c.red(f.rule)}] ({f.snippet})")

    print()
    if report.error_count == 0 and report.warning_count == 0:
        print(f"{c.green('✓ All checks passed!')}")
        return 0

    summary = f"Errors: {report.error_count} | Warnings: {report.warning_count}"
    if report.error_count > 0 or (args.strict and report.warning_count > 0):
        print(c.red(f"✗ {summary}"))
        return 1

    print(c.yellow(f"! {summary} (pass --strict to fail on warnings)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
