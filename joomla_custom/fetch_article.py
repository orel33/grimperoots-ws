#!/usr/bin/env python3
"""Fetch one article's raw database fields through the custom Joomla endpoint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

from joomla_custom.ws_client import load_settings, get_json


DEFAULT_ENV_FILE = Path(".env.local")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch one article's original database text through the custom Joomla endpoint."
    )
    parser.add_argument("article_id", type=int, help="Joomla article ID")
    parser.add_argument(
        "--env-file", type=Path, default=DEFAULT_ENV_FILE,
        help=f"Site and endpoint settings file (default: {DEFAULT_ENV_FILE}).",
    )
    parser.add_argument("--output", type=Path, help="Write JSON here instead of stdout.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Print the request without contacting Joomla.")
    mode.add_argument("--apply", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.article_id <= 0:
        parser.error("article_id must be a positive integer")

    try:
        settings = load_settings(args.env_file)
        missing = [key for key in ("SITE_URL", "GRIMPEROOTS_WS_TOKEN") if not settings.get(key)]
        if missing:
            raise ValueError(
                "Missing setting(s): " + ", ".join(missing)
                + f". Set them in {args.env_file} or in the process environment."
            )
        site = urlsplit(settings["SITE_URL"])
        if site.scheme != "https" or not site.netloc:
            raise ValueError("SITE_URL must be an https URL for the Joomla installation.")
        endpoint = urlunsplit((site.scheme, site.netloc, "/ws/article.php", "", ""))
        url = endpoint + "?" + urlencode({"id": args.article_id})
        if args.dry_run:
            print(f"Dry-run: would GET the protected custom endpoint for article {args.article_id}.")
            return 0
        article = get_json(url, settings["GRIMPEROOTS_WS_TOKEN"])
    except LookupError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    output = json.dumps(article, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
        except OSError as error:
            print(f"Could not write {args.output}: {error}", file=sys.stderr)
            return 1
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
