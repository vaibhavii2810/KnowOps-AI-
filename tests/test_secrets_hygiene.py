"""
tests/test_secrets_hygiene.py  –  Phase 10.4 (D-035)
Keeps secrets out of git. The GitHub repo is public, so a leaked key is a leaked key.

If a test here fails because of a *history* match, rotating the key is the fix — deleting the
line in a new commit does not remove it from history, and anyone can read history.
"""

import re
import subprocess
import zlib
from pathlib import Path
from urllib.parse import urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Common secret formats. Deliberately specific: a loose "password = …" regex would flag ordinary code.
SECRET_FORMATS = {
    "google-api-key": rb"AIza[0-9A-Za-z_\-]{35}",
    "gemini-style-key": rb"\bAQ\.[A-Za-z0-9_\-]{30,}",
    "neon-password": rb"npg_[A-Za-z0-9]{8,}",
    "jwt-token": rb"eyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}",
    "aws-access-key": rb"AKIA[0-9A-Z]{16}",
    "github-token": rb"gh[pousr]_[A-Za-z0-9]{36,}",
    "slack-token": rb"xox[baprs]-[A-Za-z0-9\-]{10,}",
    "slack-webhook": rb"hooks\.slack\.com/services/T[A-Z0-9]{6,}/B[A-Z0-9]{6,}/[A-Za-z0-9]{16,}",
    "private-key-block": rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    "openai-style-key": rb"\bsk-[A-Za-z0-9]{20,}",
    # a database URL with a real-looking password (the template's user:password@host is allowed)
    "db-url-with-password": rb"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^:/\s@]+:(?!password@|change-me|<)[^@\s]+@",
}
COMPILED = {name: re.compile(rx) for name, rx in SECRET_FORMATS.items()}


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, errors="replace")
    if result.returncode not in (0, 1):
        pytest.skip(f"git unavailable or not a repository: {result.stderr.strip()[:80]}")
    return result.stdout


def find_secret_formats(blob: bytes) -> list[str]:
    return [name for name, rx in COMPILED.items() if rx.search(blob)]


def pdf_text(data: bytes) -> bytes:
    """Best-effort text of a PDF: the raw bytes plus every Flate-decompressed stream."""
    chunks = [data]
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        try:
            chunks.append(zlib.decompress(match.group(1)))
        except zlib.error:
            pass
    return b"\n".join(chunks)


# ---------------------------------------------------------------------------
# The scanner itself must work, or the tests below are a silent no-op
# ---------------------------------------------------------------------------

def test_scanner_detects_each_format_it_claims_to_detect():
    # Built at runtime so this file's own source never contains a realistic secret.
    samples = {
        "google-api-key": "AIza" + "A" * 35,
        "gemini-style-key": "AQ." + "b" * 40,
        "neon-password": "npg_" + "c" * 12,
        "jwt-token": "eyJ" + "d" * 12 + ".eyJ" + "e" * 12 + "." + "f" * 12,
        "aws-access-key": "AKIA" + "G" * 16,
        "github-token": "ghp_" + "h" * 40,
        "slack-token": "xoxb-" + "1" * 12,
        "slack-webhook": "hooks.slack.com/services/T" + "A" * 8 + "/B" + "B" * 8 + "/" + "c" * 20,
        "private-key-block": "-----BEGIN RSA PRIVATE" + " KEY-----",
        "openai-style-key": "sk-" + "i" * 24,
        "db-url-with-password": "postgresql://neondb_owner:" + "s3cretvalue" + "@host/db",
    }
    assert set(samples) == set(SECRET_FORMATS)
    for name, sample in samples.items():
        assert name in find_secret_formats(sample.encode()), f"scanner does not detect {name}"


def test_scanner_allows_the_template_placeholders():
    assert find_secret_formats(b"DATABASE_URL=postgresql://user:password@host/dbname?sslmode=require") == []
    assert find_secret_formats(b"CRON_SECRET=change-me-too") == []


# ---------------------------------------------------------------------------
# 1. .env is ignored and never tracked
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [".env", ".env.local", ".env.production", ".env.development.local"])
def test_env_files_are_gitignored(path):
    ignored = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode == 0
    assert ignored, f"{path} is not gitignored"


def test_env_template_is_not_ignored():
    assert subprocess.run(["git", "check-ignore", "-q", ".env.example"], cwd=ROOT).returncode == 1


def test_only_the_template_is_tracked_among_env_files():
    tracked = [f for f in git("ls-files").splitlines() if re.search(r"(^|/)\.env", f)]
    assert tracked == [".env.example"]


def test_no_env_file_was_ever_committed_on_any_branch():
    ever = {f for f in git("log", "--all", "--full-history", "--name-only", "--format=").splitlines()
            if re.search(r"(^|/)\.env", f)}
    assert ever <= {".env.example"}, f"committed at some point: {sorted(ever - {'.env.example'})}"


def test_env_template_contains_only_placeholders():
    secret_key = re.compile(r"KEY|SECRET|PASSWORD|TOKEN|DATABASE_URL")
    placeholder = re.compile(r"change-me|your-|password@host|localhost|<")
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition("=")
        if secret_key.search(key):
            assert placeholder.search(value), f".env.example: {key} does not look like a placeholder"


# ---------------------------------------------------------------------------
# 2. No secret formats in tracked files or anywhere in history
# ---------------------------------------------------------------------------

def test_no_secret_formats_in_tracked_files():
    problems = []
    for rel in git("ls-files").splitlines():
        path = ROOT / rel
        if not path.is_file():
            continue
        data = path.read_bytes()
        if path.suffix.lower() == ".pdf":
            data = pdf_text(data)
        elif b"\x00" in data[:4096]:
            continue  # other binary files
        for name in find_secret_formats(data):
            problems.append(f"{rel}: {name}")
    assert not problems, problems


def test_no_secret_formats_were_ever_added_to_git_history():
    """Every line ever added on any branch. A hit means the key is public: rotate it."""
    patch = git("log", "--all", "-p", "--format=COMMIT %h", "--no-color")
    commit, problems = "?", []
    for line in patch.splitlines():
        if line.startswith("COMMIT "):
            commit = line.split()[1]
        elif line.startswith("+") and not line.startswith("+++"):
            for name in find_secret_formats(line.encode("utf-8", "replace")):
                problems.append(f"commit {commit}: {name}")
    assert not problems, sorted(set(problems))


def test_local_secret_values_never_appear_in_git_history():
    """Reads the real values from the local .env (skipped where there is none, e.g. CI) and
    searches all history for each. Reports only the variable name — never the value."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        pytest.skip("no local .env to read secret values from")
    values = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.strip().partition("=")
        if key == "DATABASE_URL" and urlparse(value).password:
            values["DATABASE_URL password"] = urlparse(value).password
        elif re.search(r"KEY|SECRET|PASSWORD|TOKEN", key) and len(value) >= 12:
            values[key] = value
    leaked = [name for name, value in values.items() if git("log", "--all", "--oneline", f"-S{value}").strip()]
    assert not leaked, f"these secrets appear in git history — rotate them: {leaked}"
