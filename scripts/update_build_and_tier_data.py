#!/usr/bin/env python3
"""
Refresh all external build/tier data used by the overlay advisor.

Runs scrapers + local transformers in order:
  1) slaythespire-2.com card tiers
  2) slaythespire-2.com build pages
  3) Mobalytics Ironclad builds (best-effort)
  4) guide.md -> guide_archetypes.json for all characters

Usage:
    python scripts/update_build_and_tier_data.py
    python scripts/update_build_and_tier_data.py --strict
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

PIPELINE: list[tuple[str, str, bool]] = [
    ("scrape_mobalytics_tiers.py", "Refresh Mobalytics card tier list", False),
    ("scrape_sts2_wiki_tiers.py", "Refresh STS2 wiki tier list", True),
    ("scrape_sts2_wiki_builds.py", "Refresh STS2 wiki builds", True),
    ("scrape_mobalytics_ironclad_builds.py", "Refresh Mobalytics Ironclad builds", False),
    ("build_guide_archetypes.py", "Generate guide archetype indexes", True),
]


def run_script(script_name: str, label: str) -> int:
    script = SCRIPTS / script_name
    if not script.is_file():
        print(f"[FAIL] {label}: missing {script_name}")
        return 1
    print(f"[RUN ] {label} ({script_name})")
    cmd = [sys.executable, str(script)]
    proc = subprocess.run(cmd, cwd=str(ROOT), check=False)
    if proc.returncode == 0:
        print(f"[ OK ] {label}")
    else:
        print(f"[FAIL] {label} (exit {proc.returncode})")
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh build/tier datasets used by reward advisor.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on any scraper error (default allows best-effort failures).",
    )
    args = parser.parse_args()

    failures: list[str] = []
    for script_name, label, required in PIPELINE:
        rc = run_script(script_name, label)
        if rc != 0:
            if args.strict or required:
                failures.append(label)
            else:
                print(f"[WARN] Non-blocking step failed: {label}")

    if failures:
        print("")
        print("Data update failed for:")
        for f in failures:
            print(f"- {f}")
        return 1

    print("")
    print("Data update complete.")
    print("Updated folders:")
    print("- data/tier_lists")
    print("- data/build_guides")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
