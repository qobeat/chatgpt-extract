"""Verify catalog completeness against processed export zips (zip_ledger.json).

Reads ledger entries only — no --zip paths required. Discovers export files via
``default_zips`` and ``export_search_dirs`` in config.
"""
from __future__ import annotations

import os
from typing import Any

import paths
import store_query as sq
import zip_ledger
import zip_scan_cache

try:
    import chatgpt_parse as P
    import ulog
except ImportError:  # pragma: no cover
    P = None  # type: ignore
    ulog = None  # type: ignore


def discover_zip_paths(basenames: set[str], cfg: dict | None = None) -> dict[str, str]:
    """Map export basename -> absolute path using config, env, and search dirs."""
    cfg = cfg or paths.load_config()
    found: dict[str, str] = {}
    candidates: list[str] = []
    for z in cfg.get("default_zips") or []:
        z = os.path.expanduser(str(z))
        if z and not z.startswith("/path/to/"):
            candidates.append(z)
    for key, val in os.environ.items():
        if not val.lower().endswith(".zip"):
            continue
        if key in ("GPT_ZIP", "GPT_ZIP1", "GPT_ZIP2", "GPT_ZIP3", "GPT_ZIP4") or \
                key.startswith("GPT_ZIP_"):
            candidates.append(os.path.expanduser(val))
    zip_dir = os.environ.get("GPT_ZIP_DIR")
    if zip_dir:
        zip_dir = os.path.expanduser(zip_dir)
        if os.path.isdir(zip_dir):
            try:
                for fn in os.listdir(zip_dir):
                    if fn.lower().endswith(".zip"):
                        candidates.append(os.path.join(zip_dir, fn))
            except OSError:
                pass
    for d in cfg.get("export_search_dirs") or []:
        d = os.path.expanduser(str(d))
        if not os.path.isdir(d):
            continue
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for fn in names:
            if fn.lower().endswith(".zip"):
                candidates.append(os.path.join(d, fn))
    for path in candidates:
        if not os.path.isfile(path):
            continue
        bn = os.path.basename(path)
        if bn in basenames and bn not in found:
            found[bn] = path
    return found


def classify_path_source(path: str, cfg: dict | None = None) -> str:
    """Describe where a resolved export path was discovered from."""
    cfg = cfg or paths.load_config()
    rp = os.path.realpath(path)

    for z in cfg.get("default_zips") or []:
        z = os.path.expanduser(str(z))
        if z and not z.startswith("/path/to/") and os.path.realpath(z) == rp:
            return "default_zips (config)"

    for key, val in os.environ.items():
        if not val.lower().endswith(".zip"):
            continue
        if (key in ("GPT_ZIP", "GPT_ZIP1", "GPT_ZIP2", "GPT_ZIP3", "GPT_ZIP4")
                or key.startswith("GPT_ZIP_")):
            if os.path.realpath(os.path.expanduser(val)) == rp:
                return f"${key}"

    zip_dir = os.environ.get("GPT_ZIP_DIR")
    if zip_dir:
        zip_dir = os.path.realpath(os.path.expanduser(zip_dir))
        if os.path.dirname(rp) == zip_dir:
            return "$GPT_ZIP_DIR"

    for d in cfg.get("export_search_dirs") or []:
        d = os.path.expanduser(str(d))
        if os.path.isdir(d) and os.path.dirname(rp) == os.path.realpath(d):
            return f"export_search_dirs: {d}"

    return "config"


def describe_search_sources(cfg: dict | None = None) -> list[str]:
    """Human-readable list of the export sources actually configured/present."""
    cfg = cfg or paths.load_config()
    out: list[str] = []

    n_default = sum(
        1 for z in (cfg.get("default_zips") or [])
        if str(z) and not str(z).startswith("/path/to/")
    )
    if n_default:
        out.append(f"default_zips ({n_default})")

    env_zips = sorted(
        key for key, val in os.environ.items()
        if val.lower().endswith(".zip") and (
            key in ("GPT_ZIP", "GPT_ZIP1", "GPT_ZIP2", "GPT_ZIP3", "GPT_ZIP4")
            or key.startswith("GPT_ZIP_"))
    )
    for key in env_zips:
        out.append(f"${key}")

    zip_dir = os.environ.get("GPT_ZIP_DIR")
    if zip_dir:
        out.append(f"$GPT_ZIP_DIR={os.path.expanduser(zip_dir)}")

    for d in cfg.get("export_search_dirs") or []:
        d = os.path.expanduser(str(d))
        out.append(f"export_search_dirs: {d}")

    if not out:
        out.append("none configured (set default_zips or export_search_dirs)")
    return out


def conversation_ids_in_zip(zip_path: str) -> tuple[set[str], int, str | None]:
    """Return (ids, count, error). Opens the archive and streams conversations."""
    if P is None:
        return set(), 0, "chatgpt_parse unavailable"
    ids: set[str] = set()
    if ulog is not None:
        ulog.set_quiet(True)
    try:
        for conv in P.iter_conversations(zip_path):
            cid = conv.get("id") or conv.get("conversation_id")
            if cid:
                ids.add(str(cid))
    except Exception as e:
        return set(), 0, str(e)
    finally:
        if ulog is not None:
            ulog.set_quiet(False)
    return ids, len(ids), None


def load_index(run_label: str | None = None) -> dict[str, dict]:
    p = sq.store_paths(run_label)
    path = p["index"]
    if not os.path.exists(path):
        return {}
    import json
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def zip_verify(run_label: str | None = None,
               force_zip_read: bool = False) -> dict[str, Any]:
    """Run completeness checks for all ledger-recorded exports.

    Conversation ids are served from the per-zip hash cache when an export's
    fingerprint is unchanged, so the slow full scan is skipped. Pass
    ``force_zip_read=True`` to ignore the cache and re-open every archive.
    """
    cfg = paths.load_config()
    st = sq.zip_status(run_label)
    store = st["store"]
    index = load_index(run_label)
    index_ids = set(index.keys())
    n_scanned = 0
    n_from_cache = 0

    ledger_entries = [
        e for e in st["entries"]
        if e.get("seen") is not None and int(e.get("seen") or 0) > 0
    ]

    basenames = {e["basename"] for e in ledger_entries}
    path_map = discover_zip_paths(basenames, cfg)

    rows: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    union_ids: set[str] = set()
    issues: list[str] = []

    for e in ledger_entries:
        bn = e["basename"]
        zpath = path_map.get(bn)
        row: dict[str, Any] = {
            "basename": bn,
            "export_date": e.get("export_date"),
            "size_bytes": e.get("size_bytes"),
            "path": zpath,
            "source": classify_path_source(zpath, cfg) if zpath else None,
            "file_ok": bool(zpath and os.path.isfile(zpath)),
            "parse_status": e.get("status"),
            "owns": e.get("chats_in_store", 0),
            "ledger_seen": e.get("seen"),
            "ledger_written": e.get("written"),
            "in_zip": None,
            "in_zip_error": None,
            "ids_source": None,
            "ids": set(),
        }
        if row["file_ok"] and zpath:
            ids: set[str] = set()
            n = 0
            err: str | None = None
            cached = None if force_zip_read else zip_scan_cache.get_ids(store, zpath)
            if cached is not None:
                ids, n = cached, len(cached)
                row["ids_source"] = "cache"
                n_from_cache += 1
            else:
                ids, n, err = conversation_ids_in_zip(zpath)
                row["ids_source"] = "scan"
                if not err:
                    n_scanned += 1
                    try:
                        zip_scan_cache.put_ids(store, zpath, ids)
                    except OSError:
                        pass
            row["ids"] = ids
            row["in_zip"] = n
            row["in_zip_error"] = err
            if err:
                issues.append(f"{bn}: could not read zip ({err})")
            else:
                union_ids |= ids
            seen = int(e.get("seen") or 0)
            if n != seen:
                checks.append({
                    "id": "ledger_count_drift",
                    "ok": False,
                    "detail": (f"{bn}: zip has {n:,} chats now but ledger "
                               f"recorded {seen:,} at last parse — re-run "
                               f"`gpt run --zip` if the file changed"),
                })
        elif not row["file_ok"]:
            issues.append(f"{bn}: export file not found (set GPT_ZIP_DIR / "
                          f"default_zips / export_search_dirs)")
        rows.append(row)

    rows.sort(
        key=lambda r: (r.get("export_date") or "", r.get("basename") or ""),
        reverse=True,
    )

    newest = rows[0] if rows else None
    newest_ids = newest["ids"] if newest else set()
    newest_bn = newest["basename"] if newest else None

    n_catalog = len(index_ids)
    n_newest_in_zip = newest["in_zip"] if newest and newest["in_zip"] is not None else 0
    older_only_ids = index_ids - newest_ids if newest_ids else set()
    missing_from_catalog = union_ids - index_ids
    catalog_not_in_any_zip = index_ids - union_ids if union_ids else set()

    all_files_ok = all(r["file_ok"] for r in rows) if rows else False
    checks.insert(0, {
        "id": "files_on_disk",
        "ok": all_files_ok,
        "detail": "All processed exports found on disk" if all_files_ok else
                  "One or more ledger exports missing from disk — check config paths",
    })

    all_full = all(r["parse_status"] == "full" for r in rows) if rows else False
    checks.append({
        "id": "parse_complete",
        "ok": all_full,
        "detail": "All ledger exports fully parsed (no --limit partial runs)" if all_full else
                  "Partial parse detected — re-run without --limit",
    })

    newest_ok = bool(newest and newest["file_ok"] and not newest.get("in_zip_error"))
    newest_missing = newest_ids - index_ids if newest_ids else set()
    checks.append({
        "id": "newest_in_catalog",
        "ok": newest_ok and len(newest_missing) == 0,
        "detail": (f"All {len(newest_ids):,} chats in newest export are in catalog"
                   if newest_ok and not newest_missing else
                   (f"{len(newest_missing):,} chat(s) in newest export "
                    f"missing from catalog" if newest_missing else
                    "Could not verify newest export")),
    })

    checks.append({
        "id": "catalog_in_exports",
        "ok": len(catalog_not_in_any_zip) == 0 if union_ids else n_catalog == 0,
        "detail": ("Every catalog chat appears in at least one processed export"
                   if not catalog_not_in_any_zip else
                   f"{len(catalog_not_in_any_zip):,} catalog chat(s) not found in "
                   f"any processed export on disk"),
    })

    checks.append({
        "id": "export_union",
        "ok": len(missing_from_catalog) == 0,
        "detail": ("Every chat across processed exports is in the catalog"
                   if not missing_from_catalog else
                   f"{len(missing_from_catalog):,} chat(s) in exports "
                   f"never reached the catalog — re-run gpt run --zip"),
    })

    # Older-only: in catalog but not in newest zip (often deleted before newer export).
    older_only_titles: list[str] = []
    for cid in sorted(older_only_ids, key=lambda c: index[c].get("update_date") or 0,
                      reverse=True)[:20]:
        meta = index.get(cid, {})
        older_only_titles.append(meta.get("title") or cid[:12])

    owns_on_older = sum(r["owns"] for r in rows if r["basename"] != newest_bn)
    checks.append({
        "id": "ownership_balance",
        "ok": True,
        "detail": (f"Catalog {n_catalog:,} = newest-covered "
                   f"{len(index_ids & newest_ids):,} + older-only {len(older_only_ids):,} "
                   f"(OWNS on older exports: {owns_on_older:,})"),
    })

    verdict_ok = all(c["ok"] for c in checks if c["id"] != "ownership_balance")
    if not ledger_entries:
        verdict_ok = False
        issues.append("No processed exports in zip_ledger.json — run gpt run --zip first")

    return {
        "data_root": st["data_root"],
        "ledger_path": st["ledger_path"],
        "n_processed_exports": len(rows),
        "n_zips_scanned": n_scanned,
        "n_zips_from_cache": n_from_cache,
        "forced_zip_read": force_zip_read,
        "n_catalog": n_catalog,
        "n_newest_in_zip": n_newest_in_zip,
        "n_older_only": len(older_only_ids),
        "n_union_in_exports": len(union_ids),
        "newest_basename": newest_bn,
        "search_sources": describe_search_sources(cfg),
        "rows": [{
            **{k: v for k, v in r.items() if k != "ids"},
            "n_ids": len(r["ids"]),
        } for r in rows],
        "checks": checks,
        "issues": issues,
        "older_only_sample_titles": older_only_titles,
        "verdict": "ok" if verdict_ok and not issues else "issues",
        "missing_from_catalog_count": len(missing_from_catalog),
        "catalog_not_in_exports_count": len(catalog_not_in_any_zip),
    }
