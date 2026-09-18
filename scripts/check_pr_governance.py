#!/usr/bin/env python3
"""Validate pull-request feature ownership metadata and labels."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "docs" / "team" / "feature-registry.json"
FEATURE_LINE = re.compile(
    r"(?im)^Feature-ID:\s*`?(F-[A-Z0-9]+(?:-[A-Z0-9]+)+)`?\s*$"
)
OWNER_LINE = re.compile(r"(?im)^Owner:\s*`?(DEV-[1-4])`?\s*$")
REVIEWER_LINE = re.compile(r"(?im)^Reviewer:\s*`?(DEV-[1-4])`?\s*$")
COMPLETION_LINE = re.compile(r"(?im)^Completion-Only:\s*(true|false)\s*$")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event", type=Path, help="GitHub pull_request event JSON")
    parser.add_argument(
        "--head-registry",
        type=Path,
        default=REGISTRY_PATH,
        help="registry from the PR head (defaults to the working tree)",
    )
    parser.add_argument(
        "--base-registry",
        type=Path,
        help="registry exported from the PR base branch",
    )
    args = parser.parse_args()

    event = json.loads(args.event.read_text(encoding="utf-8"))
    pull_request = event.get("pull_request")
    if pull_request is None:
        print("no pull_request payload; governance check skipped")
        return

    registry = json.loads(args.head_registry.read_text(encoding="utf-8"))
    features = {feature["id"]: feature for feature in registry["features"]}
    developers = {developer["id"]: developer for developer in registry["developers"]}
    base_features = None
    if args.base_registry:
        base = json.loads(args.base_registry.read_text(encoding="utf-8"))
        base_features = {feature["id"]: feature for feature in base["features"]}
    body = pull_request.get("body") or ""
    labels = {item["name"] for item in pull_request.get("labels", [])}
    errors: list[str] = []

    feature_match = FEATURE_LINE.search(body)
    owner_match = OWNER_LINE.search(body)
    reviewer_match = REVIEWER_LINE.search(body)
    completion_match = COMPLETION_LINE.search(body)
    if feature_match is None:
        errors.append("PR body must contain 'Feature-ID: F-...' on its own line")
    if owner_match is None:
        errors.append("PR body must contain 'Owner: DEV-N' on its own line")
    if reviewer_match is None:
        errors.append("PR body must contain 'Reviewer: DEV-N' on its own line")
    if completion_match is None:
        errors.append("PR body must contain 'Completion-Only: true|false' on its own line")

    feature = features.get(feature_match.group(1)) if feature_match else None
    owner = owner_match.group(1) if owner_match else None
    reviewer = reviewer_match.group(1) if reviewer_match else None
    completion_only = bool(
        completion_match and completion_match.group(1).lower() == "true"
    )
    if feature_match and feature is None:
        errors.append(f"unknown Feature-ID: {feature_match.group(1)}")
    if owner and owner not in developers:
        errors.append(f"unknown owner: {owner}")
    if reviewer and reviewer not in developers:
        errors.append(f"unknown reviewer: {reviewer}")

    ownership_change = "governance:ownership" in labels
    if ownership_change and completion_only:
        errors.append("ownership-change and completion-only modes cannot be combined")
    if base_features is not None:
        for feature_id, base_feature in base_features.items():
            head_feature = features.get(feature_id)
            if head_feature is None:
                if not ownership_change:
                    errors.append(f"feature {feature_id} cannot be removed without governance:ownership")
                continue
            protected = ("owner", "reviewer", "area")
            if not ownership_change and any(
                head_feature[key] != base_feature[key] for key in protected
            ):
                errors.append(
                    f"feature {feature_id} ownership fields differ from the base registry"
                )
        if feature_match and feature_match.group(1) not in base_features and not ownership_change:
            errors.append("new features require a separate governance:ownership PR")

    expected_feature = feature
    if feature and base_features and feature["id"] in base_features and not ownership_change:
        expected_feature = base_features[feature["id"]]
    if feature and owner and feature["owner"] != owner:
        errors.append(
            f"PR owner {owner} does not match registry owner {feature['owner']}"
        )
    if expected_feature and reviewer and expected_feature["reviewer"] != reviewer:
        errors.append(
            f"PR reviewer {reviewer} does not match registry reviewer "
            f"{expected_feature['reviewer']}"
        )

    owner_labels = {label for label in labels if label.startswith("owner:")}
    area_labels = {label for label in labels if label.startswith("area:")}
    status_labels = {label for label in labels if label.startswith("status:")}
    type_labels = {label for label in labels if label.startswith("type:")}
    if len(owner_labels) != 1:
        errors.append("PR must have exactly one owner:* label")
    if len(area_labels) != 1:
        errors.append("PR must have exactly one area:* label")
    if len(status_labels) != 1:
        errors.append("PR must have exactly one status:* label")
    if len(type_labels) != 1:
        errors.append("PR must have exactly one type:* label")

    if expected_feature:
        expected_owner = developers[expected_feature["owner"]]["owner_label"]
        expected_area = f"area:{expected_feature['area']}"
        expected_type = next(
            label for label in expected_feature["labels"] if label.startswith("type:")
        )
        if expected_owner not in labels:
            errors.append(f"PR requires label {expected_owner}")
        if expected_area not in labels:
            errors.append(f"PR requires label {expected_area}")
        if expected_type not in labels:
            errors.append(f"PR requires label {expected_type}")

        expected_handle = developers[expected_feature["owner"]].get("github_handle")
        author = (pull_request.get("user") or {}).get("login")
        if expected_handle and author != expected_handle:
            errors.append(
                f"PR author {author!r} does not match owner handle {expected_handle!r}"
            )
        elif not expected_handle:
            print(
                f"WARNING: {expected_feature['owner']} has no github_handle; "
                "author identity is not enforced",
                file=sys.stderr,
            )

    if pull_request.get("draft"):
        if status_labels and not status_labels.intersection(
            {"status:in-progress", "status:review"}
        ):
            errors.append("draft PR status must be in-progress or review")
    elif "status:review" not in labels:
        errors.append("non-draft PR requires status:review")
    elif feature:
        expected_status = "done" if completion_only else "review"
        if not ownership_change and feature["status"] != expected_status:
            errors.append(f"non-draft PR requires registry status {expected_status}")
        if completion_only and not feature.get("completion"):
            errors.append("completion-only PR requires completion metadata")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
    feature_id = feature["id"] if feature else "unknown"
    print(f"PR governance valid for {feature_id} owned by {owner}")


if __name__ == "__main__":
    main()
