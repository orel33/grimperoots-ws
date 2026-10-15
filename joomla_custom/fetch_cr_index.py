#!/usr/bin/env python3
"""Export the lightweight index of published CRs through the custom Joomla endpoint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

from joomla_custom.ws_client import get_json, load_settings


DEFAULT_ENV_FILE = Path(".env.local")
DEFAULT_OUTPUT = Path("data/cr_index.json")
DEFAULT_CATEGORY_ID = 33


def public_article_url(site_url: str, article_id: int) -> str:
    return f"{site_url.rstrip('/')}/{article_id}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export a lightweight index of published Joomla CRs through the custom read-only endpoint."
    )
    parser.add_argument(
        "--env-file", type=Path, default=DEFAULT_ENV_FILE,
        help=f"Site settings file (default: {DEFAULT_ENV_FILE}).",
    )
    parser.add_argument(
        "--category-id", type=int, default=DEFAULT_CATEGORY_ID,
        help=f"Root Joomla category whose descendants contain the CRs (default: {DEFAULT_CATEGORY_ID}).",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"Output JSON file (default: {DEFAULT_OUTPUT}).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Print the request without contacting Joomla.")
    mode.add_argument("--apply", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.category_id <= 0:
        parser.error("category-id must be a positive integer")

    try:
        settings = load_settings(args.env_file)
        if not settings.get("SITE_URL"):
            raise ValueError(f"Missing SITE_URL in {args.env_file} or process environment.")
        site = urlsplit(settings["SITE_URL"])
        if site.scheme != "https" or not site.netloc:
            raise ValueError("SITE_URL must be an https URL for the Joomla installation.")
        endpoint = urlunsplit((site.scheme, site.netloc, "/ws/cr-index.php", "", ""))
        url = endpoint + "?" + urlencode(
            {"category_id": args.category_id}
        )
        if args.dry_run:
            print(f"Dry-run: would GET the public CR index and save it to {args.output}.")
            return 0
        payload = get_json(url)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    records = payload.get("data")
    if not isinstance(records, list):
        print("Error: the custom endpoint returned an invalid CR index.", file=sys.stderr)
        return 1
    for article in records:
        if not isinstance(article, dict) or article.get("id") is None:
            print("Error: the custom endpoint returned an invalid article record.", file=sys.stderr)
            return 1
        article["url"] = public_article_url(settings["SITE_URL"], int(article["id"]))

    payload.setdefault("meta", {})["count"] = len(records)
    output = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    except OSError as error:
        print(f"Could not write {args.output}: {error}", file=sys.stderr)
        return 1
    print(f"Exported {len(records)} CRs to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
