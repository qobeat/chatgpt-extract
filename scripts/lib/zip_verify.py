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


def zip_verify(run_label: str | None = None) -> dict[str, Any]:
    """Run completeness checks for all ledger-recorded exports."""
    cfg = paths.load_config()
    st = sq.zip_status(run_label)
    index = load_index(run_label)
    index_ids = set(index.keys())

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
            "file_ok": bool(zpath and os.path.isfile(zpath)),
            "parse_status": e.get("status"),
            "owns": e.get("chats_in_store", 0),
            "ledger_seen": e.get("seen"),
            "ledger_written": e.get("written"),
            "in_zip": None,
            "in_zip_error": None,
            "ids": set(),
        }
        if row["file_ok"] and zpath:
            ids, n, err = conversation_ids_in_zip(zpath)
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
                    "detail": (f"{bn}: zip has {n:,} conversations now but ledger "
                               f"recorded {seen:,} at last parse — re-run "
                               f"`gpt run --zip` if the file changed"),
                })
        elif not row["file_ok"]:
            issues.append(f"{bn}: export file not found (set default_zips or "
                          f"export_search_dirs in config)")
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
        "detail": (f"All {len(newest_ids):,} conversations in newest export are in catalog"
                   if newest_ok and not newest_missing else
                   (f"{len(newest_missing):,} conversation(s) in newest export "
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
        "detail": ("Every conversation across processed exports is in the catalog"
                   if not missing_from_catalog else
                   f"{len(missing_from_catalog):,} conversation(s) in exports "
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
        "n_catalog": n_catalog,
        "n_newest_in_zip": n_newest_in_zip,
        "n_older_only": len(older_only_ids),
        "n_union_in_exports": len(union_ids),
        "newest_basename": newest_bn,
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
