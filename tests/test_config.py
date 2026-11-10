"""
tests/test_config.py  –  Phase 10 security hardening, D-063
Bug #9 (external bug report, Medium): missing env vars silently fall back to app_password="admin" and
jwt_secret="dev-secret" (D-007), so a deployment that forgot to set them is open to anyone who guesses
admin/admin and can forge tokens with the public default secret. D-007's own text named this as its
revisit condition once production security work landed — this is that revisit.

ensure_secrets_are_configured() is tested directly, against constructed stand-ins, not by re-importing
app.main: that module calls it once at real import time (before any test can monkeypatch settings.vercel),
which is exactly what makes it a safe, one-time boot check rather than something that could fire mid-test-run.
"""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import InsecureDefaultSecret, ensure_secrets_are_configured

ROOT = Path(__file__).resolve().parents[1]


def _settings(vercel="1", jwt_secret="dev-secret", app_password="admin"):
    return SimpleNamespace(vercel=vercel, jwt_secret=jwt_secret, app_password=app_password)


def test_refuses_to_start_on_vercel_with_the_default_jwt_secret():
    with pytest.raises(InsecureDefaultSecret, match="JWT_SECRET"):
        ensure_secrets_are_configured(_settings(jwt_secret="dev-secret", app_password="a-real-password"))


def test_refuses_to_start_on_vercel_with_the_default_password():
    with pytest.raises(InsecureDefaultSecret, match="APP_PASSWORD"):
        ensure_secrets_are_configured(_settings(jwt_secret="a-real-secret", app_password="admin"))


def test_refuses_to_start_on_vercel_with_both_defaults_and_names_both():
    with pytest.raises(InsecureDefaultSecret, match="JWT_SECRET, APP_PASSWORD"):
        ensure_secrets_are_configured(_settings())


def test_starts_fine_on_vercel_once_both_secrets_are_real():
    ensure_secrets_are_configured(_settings(jwt_secret="a-real-secret", app_password="a-real-password"))  # no raise


def test_insecure_defaults_are_fine_off_vercel():
    """Local dev is unaffected: the defaults exist specifically so a contributor needs no .env to run the app."""
    ensure_secrets_are_configured(_settings(vercel=""))  # no raise, even with both defaults in place


def _import_app_main(env_overrides: dict) -> subprocess.CompletedProcess:
    env = {"PATH": __import__("os").environ.get("PATH", "")}
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
    )


def test_app_main_really_fails_to_import_on_vercel_with_default_secrets():
    """The end-to-end proof, not just the pure function: a fresh process, as a real Vercel cold start would
    run it, genuinely refuses to import app.main — not something that only works when called directly."""
    result = _import_app_main({"VERCEL": "1", "JWT_SECRET": "dev-secret", "APP_PASSWORD": "admin"})
    assert result.returncode != 0
    assert "InsecureDefaultSecret" in result.stderr and "JWT_SECRET" in result.stderr


def test_app_main_imports_fine_on_vercel_with_real_secrets():
    result = _import_app_main({"VERCEL": "1", "JWT_SECRET": "a-real-secret-value", "APP_PASSWORD": "a-real-password"})
    assert result.returncode == 0, result.stderr


def test_app_main_imports_fine_off_vercel_even_with_default_secrets():
    result = _import_app_main({"JWT_SECRET": "dev-secret", "APP_PASSWORD": "admin"})  # no VERCEL at all
    assert result.returncode == 0, result.stderr
