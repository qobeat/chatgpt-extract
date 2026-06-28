"""embeddings.py — local embedding + retrieval helpers for `gpt index`/`gpt ask`.

Everything here runs against the local Ollama host (`/api/embed`), so building
the index and asking questions costs $0 and never leaves the machine. numpy is
imported lazily so this module (and the rest of the CLI) still imports cleanly
on a box without numpy — only the vector-math helpers require it.

Pieces:
  * chunk_transcript  — deterministic char-window chunks of a reduced transcript
  * resolve_embed_model / embed_texts — talk to Ollama's embedding endpoint
  * recency_weight    — decay so the *latest* chats win on near-ties
  * cosine_sims / top_indices — rank chunks against a query vector
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
from typing import Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ollama_probe  # noqa: E402

# Preference order: bge-m3 is multilingual (good for mixed RU/EN chats) and
# small; qwen3-embedding is the heavier fallback.
PREFERRED_EMBED_MODELS = ("bge-m3", "qwen3-embedding")

# Conservative defaults: ~1200 chars (~300 tokens) per chunk with 200 overlap so
# a concept spanning a window boundary still lands whole in one neighbour.
DEFAULT_CHUNK_SIZE = 1200
DEFAULT_CHUNK_OVERLAP = 200
DEFAULT_HALF_LIFE_DAYS = 180.0


class EmbeddingError(RuntimeError):
    """Raised when the embedding backend is unavailable or misbehaves."""


# ---------------------------------------------------------------------------
# Chunking (pure, no I/O, no numpy)
# ---------------------------------------------------------------------------
def chunk_transcript(text: str, *, size: int = DEFAULT_CHUNK_SIZE,
                     overlap: int = DEFAULT_CHUNK_OVERLAP
                     ) -> list[tuple[int, int, str]]:
    """Split `text` into overlapping windows.

    Returns a list of `(start, end, chunk)` with `0 <= start < end <= len(text)`.
    Deterministic: same input always yields the same windows. A short transcript
    becomes a single chunk; empty/whitespace-only text yields no chunks.
    """
    if size <= 0:
        raise ValueError("size must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must satisfy 0 <= overlap < size")
    if not text or not text.strip():
        return []
    n = len(text)
    if n <= size:
        return [(0, n, text)]
    step = size - overlap
    out: list[tuple[int, int, str]] = []
    start = 0
    while start < n:
        end = min(start + size, n)
        chunk = text[start:end]
        if chunk.strip():
            out.append((start, end, chunk))
        if end >= n:
            break
        start += step
    return out


# ---------------------------------------------------------------------------
# Embedding backend (Ollama, local)
# ---------------------------------------------------------------------------
def resolve_embed_model(host: str | None = None,
                        preferred: str | None = None) -> str:
    """Pick an installed embedding model.

    Honors an explicit `preferred` name when present on the host; otherwise
    walks PREFERRED_EMBED_MODELS, then falls back to any model whose discovered
    role is ``embedding``. Raises EmbeddingError if none is installed.
    """
    host = ollama_probe.normalize_host(host)
    models = ollama_probe.discover_models(host) or []
    names = [m.get("name", "") for m in models if m.get("name")]
    embedders = [m.get("name", "") for m in models
                 if (m.get("role") or "") == "embedding" and m.get("name")]

    def _match(want: str) -> str | None:
        if want in names:
            return want
        base = want.split(":")[0]
        for n in names:
            if n == want or n.split(":")[0] == base:
                return n
        return None

    if preferred:
        hit = _match(preferred)
        if hit:
            return hit
        raise EmbeddingError(
            f"embedding model '{preferred}' not installed on {host}. "
            f"Installed embedders: {', '.join(embedders) or '(none)'}")
    for want in PREFERRED_EMBED_MODELS:
        hit = _match(want)
        if hit:
            return hit
    if embedders:
        return embedders[0]
    raise EmbeddingError(
        f"no embedding model installed on {host}. Pull one, e.g. "
        f"`ollama pull bge-m3`, then retry.")


def _embed_client(timeout: int):
    # Reuse the provider HTTP helper (retry/backoff on 429/5xx) without pulling
    # in a full generation provider. Import is local so a missing providers pkg
    # never breaks `import embeddings`.
    from providers.base import Provider
    return Provider(model="embed", timeout=timeout, max_retries=2)


def embed_texts(texts: Sequence[str], *, model: str | None = None,
                host: str | None = None, timeout: int = 120,
                batch: int = 16) -> list[list[float]]:
    """Embed `texts` via Ollama `/api/embed`. Returns one vector per input.

    Batches requests (Ollama accepts a list `input`). Empty input -> []. Raises
    EmbeddingError on transport failure or a malformed response so callers can
    surface a single clean message.
    """
    items = list(texts)
    if not items:
        return []
    host = ollama_probe.normalize_host(host)
    model = model or resolve_embed_model(host)
    client = _embed_client(timeout)
    url = host.rstrip("/") + "/api/embed"
    out: list[list[float]] = []
    for i in range(0, len(items), max(1, batch)):
        window = items[i:i + max(1, batch)]
        try:
            data = client._post_json(
                url, {"model": model, "input": window},
                {"Content-Type": "application/json"})
        except Exception as e:  # ProviderError + anything urllib raised
            raise EmbeddingError(
                f"embedding request to {url} failed: {e}") from e
        vecs = data.get("embeddings")
        if vecs is None and "embedding" in data:  # older single-vector shape
            vecs = [data["embedding"]]
        if not isinstance(vecs, list) or len(vecs) != len(window):
            raise EmbeddingError(
                f"unexpected /api/embed response for model '{model}': "
                f"got {0 if vecs is None else len(vecs)} vectors for "
                f"{len(window)} inputs")
        out.extend([float(x) for x in v] for v in vecs)
    return out


def embed_one(text: str, **kw) -> list[float]:
    """Convenience: embed a single string (e.g. a query)."""
    vecs = embed_texts([text], **kw)
    if not vecs:
        raise EmbeddingError("embedding backend returned no vector")
    return vecs[0]


# ---------------------------------------------------------------------------
# Recency + ranking (numpy)
# ---------------------------------------------------------------------------
def _parse_date(value: str | None) -> _dt.datetime | None:
    if not value:
        return None
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    for parse in (_dt.datetime.fromisoformat,):
        try:
            dt = parse(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_dt.timezone.utc)
            return dt
        except ValueError:
            pass
    # Bare date (YYYY-MM-DD) or first 10 chars of a timestamp.
    try:
        d = _dt.date.fromisoformat(s[:10])
        return _dt.datetime(d.year, d.month, d.day, tzinfo=_dt.timezone.utc)
    except ValueError:
        return None


def recency_weight(update_date: str | None, *,
                   half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
                   now: _dt.datetime | None = None) -> float:
    """Exponential-decay multiplier in (0, 1] from a chat's update date.

    A chat updated `half_life_days` ago weighs 0.5; today's weighs ~1.0. Unknown
    or unparseable dates get a neutral 1.0 so they are ranked on similarity
    alone (never silently buried). `half_life_days <= 0` disables decay.
    """
    if half_life_days <= 0:
        return 1.0
    dt = _parse_date(update_date)
    if dt is None:
        return 1.0
    if now is None:
        now = _dt.datetime.now(_dt.timezone.utc)
    age_days = (now - dt).total_seconds() / 86400.0
    if age_days <= 0:
        return 1.0
    return float(0.5 ** (age_days / half_life_days))


def _require_numpy():
    try:
        import numpy as np  # noqa: E402
    except ImportError as e:  # pragma: no cover - exercised only without numpy
        raise EmbeddingError(
            "numpy is required for semantic search. Install it: "
            "pip install numpy (or re-run bash setup.sh)") from e
    return np


def normalize_matrix(matrix):
    """L2-normalize rows of a 2-D array; zero rows stay zero."""
    np = _require_numpy()
    m = np.asarray(matrix, dtype="float32")
    if m.ndim != 2:
        raise ValueError("matrix must be 2-D")
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms


def cosine_sims(qvec, matrix):
    """Cosine similarity of `qvec` against each row of `matrix` (1-D array)."""
    np = _require_numpy()
    q = np.asarray(qvec, dtype="float32")
    qn = np.linalg.norm(q)
    if qn == 0:
        return np.zeros(np.asarray(matrix).shape[0], dtype="float32")
    q = q / qn
    return normalize_matrix(matrix) @ q


def top_indices(scores, k: int) -> list[int]:
    """Indices of the `k` highest scores, best first (stable on ties by index)."""
    np = _require_numpy()
    s = np.asarray(scores, dtype="float32")
    n = s.shape[0]
    if n == 0 or k <= 0:
        return []
    k = min(k, n)
    # argsort is ascending; negate for descending, stable keeps lower index
    # first on exact ties (deterministic output).
    order = np.argsort(-s, kind="stable")[:k]
    return [int(i) for i in order]
