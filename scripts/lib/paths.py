"""Resolve data paths from RECONSTRUCTOR_DATA_ROOT env or local config."""
from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_local_config() -> dict:
    path = os.path.join(ROOT, "config", "reconstruct.config.local.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_config() -> dict:
    """Load committed defaults merged with optional local overrides."""
    base_path = os.path.join(ROOT, "config", "reconstruct.config.json")
    cfg: dict = {}
    if os.path.exists(base_path):
        with open(base_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    cfg.update(_load_local_config())
    return cfg


def package_info() -> dict:
    """Authoritative package identity (name/version) from `package-info.json`.

    This is the consuming codepath that keeps the file governed rather than
    orphaned (NFR-Q7): `gpt --version` reads it, and `test_release_coherence`
    asserts it agrees with the README H1 and the top `CHANGELOG.md` heading.
    """
    path = os.path.join(ROOT, "package-info.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def changelog_version() -> tuple[str, str]:
    """`(version, name)` from the top `## X.Y.Z — NAME — DATE` heading in
    `CHANGELOG.md` — the single source of truth for the current release."""
    import re
    path = os.path.join(ROOT, "CHANGELOG.md")
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^##\s+([0-9]+\.[0-9]+\.[0-9]+)\s+—\s+([^—]+?)\s+—",
                         line.strip())
            if m:
                return m.group(1), m.group(2).strip()
    raise ValueError("no '## X.Y.Z — NAME — DATE' heading found in CHANGELOG.md")


def data_root() -> str | None:
    env = os.environ.get("RECONSTRUCTOR_DATA_ROOT")
    if env:
        return os.path.expanduser(env)
    cfg = _load_local_config()
    root = cfg.get("data_root")
    if root:
        return os.path.expanduser(str(root))
    return None


def _base() -> str:
    root = data_root()
    if root:
        return root
    return os.path.join(ROOT, "output")


def run_root(run_label: str) -> str:
    """Root directory for an isolated run: output/runs/<label> or $DATA_ROOT/runs/<label>."""
    return os.path.join(_base(), "runs", run_label)


def update_latest_pointer(run_label: str) -> str:
    """
    Point output/runs/latest at the most recent run label.
    Uses a symlink when possible; falls back to a one-line text file.
    """
    runs_dir = os.path.join(_base(), "runs")
    os.makedirs(runs_dir, exist_ok=True)
    target = os.path.join(runs_dir, run_label)
    os.makedirs(target, exist_ok=True)
    pointer = os.path.join(runs_dir, "latest")
    try:
        if os.path.islink(pointer) or os.path.exists(pointer):
            os.remove(pointer)
        os.symlink(target, pointer)
    except OSError:
        with open(pointer, "w", encoding="utf-8") as f:
            f.write(run_label + "\n")
    return pointer


def store_dir(explicit: str | None = None, run_label: str | None = None) -> str:
    if explicit:
        return explicit
    if run_label:
        return os.path.join(run_root(run_label), "store")
    root = data_root()
    if root:
        return os.path.join(root, "store")
    return os.path.join(ROOT, "output", "store")


def bundles_dir(explicit: str | None = None, run_label: str | None = None) -> str:
    if explicit:
        return explicit
    if run_label:
        return os.path.join(run_root(run_label), "bundles")
    root = data_root()
    if root:
        return os.path.join(root, "bundles")
    return os.path.join(ROOT, "output", "bundles")


def reconstructed_json(explicit: str | None = None, run_label: str | None = None) -> str:
    if explicit:
        return explicit
    if run_label:
        return os.path.join(run_root(run_label), "reconstructed_projects.json")
    root = data_root()
    if root:
        return os.path.join(root, "reconstructed_projects.json")
    return os.path.join(ROOT, "output", "reconstructed_projects.json")


def index_dir(explicit: str | None = None, run_label: str | None = None) -> str:
    """Directory for the semantic embedding index (gpt index / gpt ask)."""
    if explicit:
        return explicit
    if run_label:
        return os.path.join(run_root(run_label), "index")
    root = data_root()
    if root:
        return os.path.join(root, "index")
    return os.path.join(ROOT, "output", "index")


def run_data_root(store: str | None = None, run_label: str | None = None) -> str:
    """Directory for run logs, summaries, and manifests."""
    if run_label:
        return run_root(run_label)
    if store:
        return os.path.abspath(os.path.dirname(store))
    return _base()


def runs_dir() -> str:
    return os.path.join(_base(), "runs")


def catalog_path() -> str:
    return os.path.join(runs_dir(), "catalog.json")


def run_manifest_path(run_label: str) -> str:
    return os.path.join(run_root(run_label), "run.json")


def resolve_run_label(label: str | None = None) -> str | None:
    """Return an explicit label, or resolve ``latest`` from runs/latest."""
    if not label:
        return None
    if label != "latest":
        return label
    pointer = os.path.join(runs_dir(), "latest")
    if os.path.islink(pointer):
        target = os.readlink(pointer)
        return os.path.basename(target.rstrip("/"))
    if os.path.isfile(pointer):
        with open(pointer, encoding="utf-8") as f:
            resolved = f.read().strip()
            if resolved:
                return resolved
    cat_path = catalog_path()
    if os.path.isfile(cat_path):
        with open(cat_path, encoding="utf-8") as f:
            latest = json.load(f).get("latest")
        if latest:
            return str(latest)
    return None


def legacy_layout_paths() -> dict[str, str]:
    """Top-level legacy artifact paths (pre run-label schema)."""
    base = _base()
    return {
        "base": base,
        "store": os.path.join(base, "store"),
        "bundles": os.path.join(base, "bundles"),
        "reconstructed": os.path.join(base, "reconstructed_projects.json"),
    }


def legacy_output_detected() -> bool:
    """True when un-migrated artifacts exist at the data root."""
    legacy = legacy_layout_paths()
    store_index = os.path.join(legacy["store"], "index.json")
    return os.path.isfile(store_index) and os.path.getsize(store_index) > 2


def published_json(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    return os.path.join(ROOT, "published", "projects.json")
