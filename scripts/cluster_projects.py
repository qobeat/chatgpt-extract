#!/usr/bin/env python3
"""
cluster_projects.py  (Cluster — deterministic, zero-LLM)

Group conversation cards into project clusters using a union-find over shared
slugs (zip-basename slugs are strong; title slugs are weak tie-breakers).
Emits output/store/clusters.json: a list of clusters, each with the
deterministic facts an LLM should NOT have to infer (dates, version zips,
file artifacts, member conversation ids).

Usage:
  python scripts/cluster_projects.py --store output/store \
      [--min-slug-votes 3]
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
import interrupt  # noqa: E402
import ulog  # noqa: E402


class UnionFind:
    def __init__(self):
        self.parent: Dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def primary_slug(card: dict, min_votes: int) -> str:
    votes = card.get("slug_votes") or {}
    if not votes:
        return slug_fallback(card)
    # prefer strongest vote; require min_votes else fall back to title slug
    best = max(votes.items(), key=lambda kv: kv[1])
    if best[1] >= min_votes:
        return best[0]
    return slug_fallback(card)


def slug_fallback(card: dict) -> str:
    votes = card.get("slug_votes") or {}
    if votes:
        return max(votes.items(), key=lambda kv: kv[1])[0]
    return "unclustered-" + card["id"][:8]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Cluster: group conversation cards into projects "
                    "(union-find over zip-basename slugs).")
    ap.add_argument("--store", default="output/store",
                    help="Store directory containing cards.jsonl (default: output/store).")
    ap.add_argument("--min-slug-votes", type=int, default=3,
                    help="Min vote weight for a zip-derived slug to be primary (default: 3).")
    ap.add_argument("--merge-cap", type=int, default=12,
                    help="Max conversations a NON-version (title-only) slug may "
                         "merge before it is treated as generic noise and left as "
                         "singletons (guards ados-profile-style mega-merges; "
                         "default: 12). Version-backed slugs are never capped.")
    args = ap.parse_args()
    ulog.set_stage("Cluster")

    cards_path = os.path.join(args.store, "cards.jsonl")
    cards: List[dict] = []
    try:
        with open(cards_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    cards.append(json.loads(line))
        ulog.log("READ", cards_path, status=f"{len(cards)} cards")
    except OSError as e:
        ulog.err("READ", cards_path, error=e)
        return 1

    uf = UnionFind()
    # Strong slugs come only from REAL version zips (junk attachment hashes /
    # bare-numeric zips were already filtered out in extract_cards).
    strong_slugs: set[str] = set()
    for c in cards:
        for z in c.get("zip_files") or []:
            if z.get("is_version") and z.get("slug"):
                strong_slugs.add(z["slug"])

    slug_to_cards: Dict[str, List[str]] = defaultdict(list)
    card_primary: Dict[str, str] = {}
    for c in cards:
        cid = c["id"]
        card_primary[cid] = primary_slug(c, args.min_slug_votes)
        strong = {z["slug"] for z in (c.get("zip_files") or [])
                  if z.get("is_version") and z.get("slug")}
        for s in strong:
            slug_to_cards[s].append(cid)
    # Version-backed slugs always merge (true project versions).
    for s, ids in slug_to_cards.items():
        for other in ids[1:]:
            uf.union(ids[0], other)

    # Title/primary-slug grouping: merge ONLY when corroborated — either the
    # slug is version-backed, or the group is small enough to not be a generic
    # catch-all. A generic slug shared by > merge_cap unrelated chats stays as
    # singletons (prevents the 306-conversation ados-profile blob).
    by_primary: Dict[str, List[str]] = defaultdict(list)
    for cid, s in card_primary.items():
        by_primary[s].append(cid)
    for s, ids in by_primary.items():
        if len(ids) < 2:
            continue
        if s in strong_slugs or len(ids) <= args.merge_cap:
            for other in ids[1:]:
                uf.union(ids[0], other)
        else:
            ulog.log("MERGE guard", s,
                     status=f"{len(ids)} convs > cap {args.merge_cap}; "
                            f"left as singletons (generic slug)")

    groups: Dict[str, List[dict]] = defaultdict(list)
    by_id = {c["id"]: c for c in cards}
    for c in cards:
        groups[uf.find(c["id"])].append(c)

    clusters = []
    for root, members in groups.items():
        members.sort(key=lambda c: c.get("create_time") or 0)
        # choose canonical slug = most common primary among members
        slug_counts: Dict[str, int] = defaultdict(int)
        for m in members:
            slug_counts[card_primary[m["id"]]] += 1
        slug = max(slug_counts.items(), key=lambda kv: kv[1])[0]

        zips: Dict[str, dict] = {}
        files: set = set()
        agg_ctypes: Dict[str, int] = defaultdict(int)
        agg_ext: Dict[str, int] = defaultdict(int)
        n_turns = n_user = n_assistant = 0
        has_code = has_image = False
        title_kw: Dict[str, int] = defaultdict(int)
        for m in members:
            for z in m.get("zip_files") or []:
                zips.setdefault(z["filename"].lower(), z)
            files.update(m.get("file_artifacts") or [])
            sig = m.get("signals") or {}
            for k, v in (sig.get("content_types") or {}).items():
                agg_ctypes[k] += v
            for k, v in (sig.get("file_ext_classes") or {}).items():
                agg_ext[k] += v
            n_turns += sig.get("n_turns", 0)
            n_user += sig.get("n_user_turns", 0)
            n_assistant += sig.get("n_assistant_turns", 0)
            has_code = has_code or bool(sig.get("has_code"))
            has_image = has_image or bool(sig.get("has_image_asset"))
            for kw in sig.get("title_keywords") or []:
                title_kw[kw] += 1

        # Only REAL version zips count as versions/Passes.
        version_zips = [z for z in zips.values() if z.get("is_version")]
        other_zips = [z for z in zips.values() if not z.get("is_version")]
        zip_list = sorted(version_zips,
                          key=lambda z: (z.get("version") or "", z["filename"]))

        top_kw = sorted(title_kw.items(), key=lambda kv: -kv[1])[:10]
        signal_summary = {
            "content_types": dict(agg_ctypes),
            "file_ext_classes": dict(agg_ext),
            "n_turns": n_turns,
            "n_user_turns": n_user,
            "n_assistant_turns": n_assistant,
            "has_code": has_code,
            "has_image_asset": has_image,
            "n_version_zips": len(version_zips),
            "n_other_zips": len(other_zips),
            "top_title_keywords": [k for k, _ in top_kw],
        }

        dates = [m.get("create_date") for m in members if m.get("create_date")]
        clusters.append({
            "slug": slug,
            "member_ids": [m["id"] for m in members],
            "titles": [m["title"] for m in members],
            "start_date": min(dates) if dates else None,
            "end_date": max(dates) if dates else None,
            "n_conversations": len(members),
            "version_zip_files": zip_list,
            "n_versions": len(zip_list),
            "n_passes": len(zip_list),
            "file_artifacts": sorted(files),
            "signal_summary": signal_summary,
        })

    clusters.sort(key=lambda c: (-c["n_conversations"], c["slug"]))
    out = os.path.join(args.store, "clusters.json")
    try:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(clusters, f, ensure_ascii=False, indent=2)
        ulog.log("WRITE", out, status=f"{len(clusters)} clusters")
    except OSError as e:
        ulog.err("WRITE", out, error=e)
        return 1
    for c in clusters[:15]:
        print(f"  {c['slug']:<28} chats={c['n_conversations']:<3} "
              f"versions={c['n_versions']:<3} {c['start_date']}..{c['end_date']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(interrupt.run_cli(main, "gpt run · cluster"))
