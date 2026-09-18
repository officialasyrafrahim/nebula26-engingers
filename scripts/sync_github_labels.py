#!/usr/bin/env python3
"""Create or update repository labels through the GitHub CLI."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABELS_PATH = ROOT / ".github" / "labels.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="OWNER/REPO; defaults to the current gh repository")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))["labels"]
    for label in labels:
        command = [
            "gh",
            "label",
            "create",
            label["name"],
            "--color",
            label["color"],
            "--description",
            label["description"],
            "--force",
        ]
        if args.repo:
            command.extend(["--repo", args.repo])
        print(shlex.join(command))
        if not args.dry_run:
            subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
