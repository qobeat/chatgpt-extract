"""
ollama_probe.py — adapter to ollama-test for host/model discovery and preflight.

Reuses ~/dev/WSL/ollama/ollama-test when available; falls back to direct HTTP.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_OLLAMA_TEST_HOME = os.path.expanduser("~/dev/WSL/ollama/ollama-test")
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"

_ollama_test_loaded = False


def _load_local_config() -> dict:
    path = os.path.join(ROOT, "config", "reconstruct.config.local.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_base_config() -> dict:
    path = os.path.join(ROOT, "config", "reconstruct.config.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def ollama_test_home() -> str:
    env = os.environ.get("OLLAMA_TEST_HOME")
    if env:
        return os.path.expanduser(env)
    cfg = _load_base_config()
    cfg.update(_load_local_config())
    home = cfg.get("ollama_test_home")
    if home:
        return os.path.expanduser(str(home))
    return DEFAULT_OLLAMA_TEST_HOME


def _ensure_ollama_test() -> bool:
    global _ollama_test_loaded
    if _ollama_test_loaded:
        return True
    home = ollama_test_home()
    if not os.path.isdir(home):
        return False
    if home not in sys.path:
        sys.path.insert(0, home)
    try:
        import ollama_test.core  # noqa: F401
        _ollama_test_loaded = True
        return True
    except Exception:
        return False


def normalize_host(host: str | None = None) -> str:
    raw = host or os.environ.get("OLLAMA_HOST") or DEFAULT_OLLAMA_HOST
    raw = raw.strip().rstrip("/")
    if not raw.startswith("http"):
        raw = "http://" + raw
    return raw


def _http_json(host: str, path: str, method: str = "GET",
               payload: dict | None = None, timeout: int = 10) -> tuple[int, Any, str | None]:
    url = normalize_host(host).rstrip("/") + path
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}, None
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
        except Exception:
            err_body = str(e)
        return e.code, None, err_body
    except Exception as e:
        return 0, None, str(e)


def host_available(host: str | None = None) -> bool:
    host = normalize_host(host)
    if _ensure_ollama_test():
        try:
            from ollama_test.core import ollama_version
            os.environ.setdefault("OLLAMA_HOST", host)
            info = ollama_version()
            return bool(info.get("available"))
        except Exception:
            pass
    status, data, err = _http_json(host, "/api/version", timeout=3)
    return status == 200 and data is not None and err is None


def host_info(host: str | None = None) -> dict[str, Any]:
    host = normalize_host(host)
    if _ensure_ollama_test():
        try:
            from ollama_test.core import ollama_version
            os.environ.setdefault("OLLAMA_HOST", host)
            return ollama_version()
        except Exception:
            pass
    status, data, err = _http_json(host, "/api/version", timeout=3)
    return {
        "host": host,
        "available": status == 200 and err is None,
        "version": (data or {}).get("version") if data else None,
        "error": err,
    }


def installed_models(host: str | None = None) -> list[str]:
    host = normalize_host(host)
    if _ensure_ollama_test():
        try:
            from ollama_test.core import list_tags
            os.environ.setdefault("OLLAMA_HOST", host)
            tags = list_tags()
            return [t["name"] for t in tags if t.get("name")]
        except Exception:
            pass
    status, data, err = _http_json(host, "/api/tags", timeout=10)
    if status != 200 or not data or err:
        return []
    models = data.get("models") or []
    return [m["name"] for m in models if m.get("name")]


def model_present(model: str, host: str | None = None) -> bool:
    names = installed_models(host)
    if model in names:
        return True
    # Allow partial match on tag (e.g. gpt-oss:20b vs gpt-oss:latest)
    base = model.split(":")[0]
    return any(n == model or n.startswith(base + ":") for n in names)


def model_context_length(model: str, host: str | None = None) -> int | None:
    host = normalize_host(host)
    if _ensure_ollama_test():
        try:
            from ollama_test.core import show_model
            os.environ.setdefault("OLLAMA_HOST", host)
            show = show_model(model) or {}
            for key in ("model_info", "details", "parameters"):
                block = show.get(key) or {}
                if isinstance(block, dict):
                    for ctx_key in ("context_length", "num_ctx"):
                        val = block.get(ctx_key)
                        if val:
                            return int(val)
            modinfo = show.get("modelfile") or ""
            for line in str(modinfo).splitlines():
                if "num_ctx" in line.lower():
                    parts = line.split()
                    for i, p in enumerate(parts):
                        if p.lower() == "num_ctx" and i + 1 < len(parts):
                            try:
                                return int(parts[i + 1])
                            except ValueError:
                                pass
        except Exception:
            pass
    status, data, err = _http_json(host, "/api/show", method="POST",
                                   payload={"model": model}, timeout=15)
    if status != 200 or not data or err:
        return None
    details = data.get("details") or {}
    if details.get("context_length"):
        return int(details["context_length"])
    return None


def discover_models(host: str | None = None) -> list[dict[str, Any]]:
    host = normalize_host(host)
    if _ensure_ollama_test():
        try:
            from ollama_test.cli import discover_models as _discover
            os.environ.setdefault("OLLAMA_HOST", host)
            return _discover(verbose=False)
        except Exception:
            pass
    return [{"name": n} for n in installed_models(host)]


def run_generation_probe(model: str, host: str | None = None,
                         timeout: int = 100) -> dict[str, Any] | None:
    """Quick smoke probe via ollama-test; returns None if unavailable."""
    host = normalize_host(host)
    if not _ensure_ollama_test():
        return None
    try:
        from ollama_test.cli import discover_models as _discover, run_generation_probe as _probe
        os.environ.setdefault("OLLAMA_HOST", host)
        model_info = None
        for m in _discover(verbose=False):
            if m.get("name") == model:
                model_info = m
                break
        if model_info is None:
            model_info = {"name": model, "capabilities": ["completion"]}
        return _probe(model_info, timeout=timeout, progress=False)
    except Exception:
        return None


def preflight(model: str, host: str | None = None, num_ctx: int | None = None) -> tuple[bool, str]:
    """
    Verify Ollama host and model before a long summarize run.
    Returns (ok, message).
    """
    host = normalize_host(host)
    if not host_available(host):
        return False, (
            f"Ollama host unreachable at {host}. "
            f"Start Ollama or run: ./ollama_test.sh status"
        )
    if not model_present(model, host):
        available = ", ".join(installed_models(host)[:12]) or "(none)"
        return False, (
            f"Model '{model}' not found. Installed: {available}. "
            f"Run: ./ollama_test.sh models"
        )
    if num_ctx is not None:
        ctx_len = model_context_length(model, host)
        if ctx_len and num_ctx > ctx_len:
            return False, (
                f"Requested num_ctx={num_ctx} exceeds model metadata "
                f"context_length={ctx_len} for '{model}'. "
                f"Lower --num-ctx or pick another model."
            )
    return True, "ok"
