#!/usr/bin/env python3
"""Validate, query and update the feature ownership registry."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "docs" / "team" / "feature-registry.json"
LABELS_PATH = ROOT / ".github" / "labels.json"
STATUSES = {"backlog", "ready", "in-progress", "review", "done", "blocked"}
FEATURE_ID = re.compile(r"^F-[A-Z0-9]+(?:-[A-Z0-9]+)+$")
HEX_COLOR = re.compile(r"^[0-9A-Fa-f]{6}$")


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_registry(registry: dict) -> None:
    registry["updated_on"] = datetime.now(timezone.utc).date().isoformat()
    REGISTRY_PATH.write_text(
        f"{json.dumps(registry, indent=2, ensure_ascii=True)}\n",
        encoding="utf-8",
    )


def validate_registry(registry: dict, labels_document: dict) -> list[str]:
    errors: list[str] = []
    developers = registry.get("developers", [])
    features = registry.get("features", [])
    known_labels = {label.get("name") for label in labels_document.get("labels", [])}
    developer_by_id = {developer.get("id"): developer for developer in developers}

    if len(known_labels) != len(labels_document.get("labels", [])):
        errors.append("labels.json contains duplicate label names")
    for label in labels_document.get("labels", []):
        if not HEX_COLOR.match(label.get("color", "")):
            errors.append(f"label {label.get('name')!r} must have a six-digit hex color")

    if registry.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if len(developer_by_id) != 4:
        errors.append("registry must define exactly four unique developers")
    handles = [developer.get("github_handle") for developer in developers]
    configured_handles = [handle for handle in handles if handle]
    if len(configured_handles) != len(set(configured_handles)):
        errors.append("configured github_handle values must be unique")

    for developer in developers:
        developer_id = developer.get("id")
        if not developer_id or developer_id not in {"DEV-1", "DEV-2", "DEV-3", "DEV-4"}:
            errors.append(f"invalid developer id: {developer_id!r}")
            continue
        if developer.get("review_partner") not in developer_by_id:
            errors.append(f"{developer_id}: unknown review_partner")
        if developer.get("review_partner") == developer_id:
            errors.append(f"{developer_id}: review_partner must be another developer")
        if developer.get("owner_label") not in known_labels:
            errors.append(f"{developer_id}: owner_label is not defined in labels.json")
        if not developer.get("primary_paths"):
            errors.append(f"{developer_id}: primary_paths cannot be empty")

    feature_ids: set[str] = set()
    for feature in features:
        feature_id = feature.get("id", "<missing-id>")
        prefix = f"{feature_id}:"
        if not FEATURE_ID.match(feature_id):
            errors.append(f"{prefix} invalid feature id")
        if feature_id in feature_ids:
            errors.append(f"{prefix} duplicate feature id")
        feature_ids.add(feature_id)

        owner = feature.get("owner")
        reviewer = feature.get("reviewer")
        if owner not in developer_by_id:
            errors.append(f"{prefix} unknown owner {owner!r}")
            continue
        if reviewer not in developer_by_id:
            errors.append(f"{prefix} unknown reviewer {reviewer!r}")
        if reviewer == owner:
            errors.append(f"{prefix} owner and reviewer must differ")

        status = feature.get("status")
        if status not in STATUSES:
            errors.append(f"{prefix} invalid status {status!r}")
        area = feature.get("area")
        labels = feature.get("labels", [])
        expected = {
            developer_by_id[owner]["owner_label"],
            f"area:{area}",
            f"status:{status}",
        }
        missing = expected.difference(labels)
        if missing:
            errors.append(f"{prefix} missing derived labels {sorted(missing)}")
        owner_labels = [label for label in labels if label.startswith("owner:")]
        status_labels = [label for label in labels if label.startswith("status:")]
        area_labels = [label for label in labels if label.startswith("area:")]
        type_labels = [label for label in labels if label.startswith("type:")]
        if len(owner_labels) != 1 or len(status_labels) != 1 or len(area_labels) != 1:
            errors.append(f"{prefix} must have one owner, area and status label")
        if len(type_labels) != 1:
            errors.append(f"{prefix} must have exactly one type label")
        unknown = set(labels).difference(known_labels)
        if unknown:
            errors.append(f"{prefix} unknown labels {sorted(unknown)}")

        if not feature.get("title") or not feature.get("requirements"):
            errors.append(f"{prefix} title and requirements are required")
        if not feature.get("paths"):
            errors.append(f"{prefix} paths cannot be empty")
        points = feature.get("estimate_points")
        if not isinstance(points, int) or points <= 0:
            errors.append(f"{prefix} estimate_points must be a positive integer")

        completion = feature.get("completion")
        if status == "done":
            if not isinstance(completion, dict):
                errors.append(f"{prefix} done features require completion metadata")
            elif completion.get("completed_by") != owner or not completion.get("reference"):
                errors.append(f"{prefix} completion must identify the owner and reference")
        elif completion is not None:
            errors.append(f"{prefix} only done features may have completion metadata")

    return errors


def validate_or_exit(registry: dict) -> None:
    errors = validate_registry(registry, load_json(LABELS_PATH))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)


def find_feature(registry: dict, feature_id: str) -> dict:
    for feature in registry["features"]:
        if feature["id"] == feature_id:
            return feature
    raise SystemExit(f"unknown feature: {feature_id}")


def replace_label(labels: list[str], prefix: str, value: str) -> list[str]:
    retained = [label for label in labels if not label.startswith(prefix)]
    retained.append(value)
    return retained


def set_owner_and_status(registry: dict, feature: dict, owner_id: str, status: str) -> None:
    developers = {developer["id"]: developer for developer in registry["developers"]}
    if owner_id not in developers:
        raise SystemExit(f"unknown developer: {owner_id}")
    developer = developers[owner_id]
    feature["owner"] = owner_id
    feature["reviewer"] = developer["review_partner"]
    feature["status"] = status
    feature["completion"] = None
    feature["labels"] = replace_label(
        feature["labels"], "owner:", developer["owner_label"]
    )
    feature["labels"] = replace_label(
        feature["labels"], "status:", f"status:{status}"
    )


def command_validate(args: argparse.Namespace) -> None:
    registry = load_json(REGISTRY_PATH)
    validate_or_exit(registry)
    print(
        f"feature registry valid: {len(registry['developers'])} developers, "
        f"{len(registry['features'])} features"
    )


def command_list(args: argparse.Namespace) -> None:
    registry = load_json(REGISTRY_PATH)
    validate_or_exit(registry)
    features = registry["features"]
    if args.owner:
        features = [feature for feature in features if feature["owner"] == args.owner]
    if args.status:
        features = [feature for feature in features if feature["status"] == args.status]
    if args.area:
        features = [feature for feature in features if feature["area"] == args.area]
    print("ID                 OWNER  STATUS       PTS  TITLE")
    for feature in sorted(features, key=lambda item: (item["owner"], item["id"])):
        print(
            f"{feature['id']:<18} {feature['owner']:<6} "
            f"{feature['status']:<12} {feature['estimate_points']:>3}  {feature['title']}"
        )


def command_show(args: argparse.Namespace) -> None:
    registry = load_json(REGISTRY_PATH)
    validate_or_exit(registry)
    print(json.dumps(find_feature(registry, args.feature_id), indent=2))


def command_claim(args: argparse.Namespace) -> None:
    registry = load_json(REGISTRY_PATH)
    feature = find_feature(registry, args.feature_id)
    if feature["status"] == "done":
        raise SystemExit("done features cannot be claimed; create a follow-up feature")
    set_owner_and_status(registry, feature, args.owner, "in-progress")
    validate_or_exit(registry)
    write_registry(registry)
    print(f"claimed {args.feature_id} for {args.owner}; reviewer={feature['reviewer']}")


def command_set_status(args: argparse.Namespace) -> None:
    if args.status == "done":
        raise SystemExit("use the complete command to set status done")
    registry = load_json(REGISTRY_PATH)
    feature = find_feature(registry, args.feature_id)
    if feature["status"] == "done":
        raise SystemExit("done features are immutable; create a follow-up feature")
    set_owner_and_status(registry, feature, feature["owner"], args.status)
    validate_or_exit(registry)
    write_registry(registry)
    print(f"{args.feature_id} status={args.status}")


def command_complete(args: argparse.Namespace) -> None:
    registry = load_json(REGISTRY_PATH)
    feature = find_feature(registry, args.feature_id)
    if feature["owner"] != args.developer:
        raise SystemExit(
            f"{args.developer} cannot complete a feature owned by {feature['owner']}"
        )
    if feature["status"] != "review":
        raise SystemExit(
            f"{args.feature_id} must be in review before completion; "
            f"current status={feature['status']}"
        )
    developer = next(
        item for item in registry["developers"] if item["id"] == args.developer
    )
    expected_handle = developer.get("github_handle")
    if expected_handle:
        actual_handle = authenticated_github_user()
        if actual_handle != expected_handle:
            raise SystemExit(
                f"authenticated GitHub user {actual_handle!r} does not match "
                f"{args.developer} handle {expected_handle!r}"
            )
    else:
        print(
            f"WARNING: {args.developer} has no github_handle; completion identity is declared",
            file=sys.stderr,
        )
    feature["status"] = "done"
    feature["labels"] = replace_label(feature["labels"], "status:", "status:done")
    feature["completion"] = {
        "completed_by": args.developer,
        "completed_on": datetime.now(timezone.utc).date().isoformat(),
        "reference": args.ref,
    }
    validate_or_exit(registry)
    write_registry(registry)
    print(f"completed {args.feature_id} by {args.developer}; reference={args.ref}")


def authenticated_github_user() -> str:
    actor = os.environ.get("GITHUB_ACTOR")
    if actor:
        return actor
    try:
        result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise SystemExit(
            "cannot verify completion identity; set GITHUB_ACTOR or authenticate gh"
        ) from exc
    return result.stdout.strip()


def command_add(args: argparse.Namespace) -> None:
    registry = load_json(REGISTRY_PATH)
    if any(feature["id"] == args.feature_id for feature in registry["features"]):
        raise SystemExit(f"feature already exists: {args.feature_id}")
    developers = {developer["id"]: developer for developer in registry["developers"]}
    developer = developers[args.owner]
    feature = {
        "id": args.feature_id,
        "title": args.title,
        "owner": args.owner,
        "reviewer": developer["review_partner"],
        "area": args.area,
        "status": "ready",
        "milestone": args.milestone,
        "estimate_points": args.points,
        "requirements": args.requirement,
        "acceptance_tests": args.acceptance,
        "paths": args.path,
        "labels": [
            developer["owner_label"],
            f"area:{args.area}",
            "status:ready",
            f"type:{args.type}",
        ],
        "completion": None,
    }
    registry["features"].append(feature)
    validate_or_exit(registry)
    write_registry(registry)
    print(f"added {args.feature_id}; owner={args.owner}; reviewer={feature['reviewer']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(required=True)

    validate = subparsers.add_parser("validate", help="validate registry and labels")
    validate.set_defaults(function=command_validate)

    listing = subparsers.add_parser("list", help="list delegated features")
    listing.add_argument("--owner", choices=["DEV-1", "DEV-2", "DEV-3", "DEV-4"])
    listing.add_argument("--status", choices=sorted(STATUSES))
    listing.add_argument("--area")
    listing.set_defaults(function=command_list)

    show = subparsers.add_parser("show", help="show one feature")
    show.add_argument("feature_id")
    show.set_defaults(function=command_show)

    add = subparsers.add_parser("add", help="add a ready feature to the registry")
    add.add_argument("feature_id")
    add.add_argument("--title", required=True)
    add.add_argument("--owner", required=True, choices=["DEV-1", "DEV-2", "DEV-3", "DEV-4"])
    add.add_argument("--area", required=True)
    add.add_argument("--type", default="feature", choices=["feature", "bug", "tech-debt", "test", "docs"])
    add.add_argument("--points", required=True, type=int)
    add.add_argument("--milestone", default="production-hardening")
    add.add_argument("--requirement", required=True, action="append")
    add.add_argument("--acceptance", action="append", default=[])
    add.add_argument("--path", required=True, action="append")
    add.set_defaults(function=command_add)

    claim = subparsers.add_parser("claim", help="claim and start a feature")
    claim.add_argument("feature_id")
    claim.add_argument("owner", choices=["DEV-1", "DEV-2", "DEV-3", "DEV-4"])
    claim.set_defaults(function=command_claim)

    status = subparsers.add_parser("set-status", help="change a non-done status")
    status.add_argument("feature_id")
    status.add_argument("status", choices=sorted(STATUSES.difference({"done"})))
    status.set_defaults(function=command_set_status)

    complete = subparsers.add_parser("complete", help="mark a feature done with evidence")
    complete.add_argument("feature_id")
    complete.add_argument("developer", choices=["DEV-1", "DEV-2", "DEV-3", "DEV-4"])
    complete.add_argument("--ref", required=True, help="PR, commit or release reference")
    complete.set_defaults(function=command_complete)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.function(args)


if __name__ == "__main__":
    main()
