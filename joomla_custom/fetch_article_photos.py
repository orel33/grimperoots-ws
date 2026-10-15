#!/usr/bin/env python3
"""Fetch the photo inventory JSON for one Joomla article."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

from joomla_custom.ws_client import get_json, load_settings


DEFAULT_ENV_FILE = Path(".env.local")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch one article's photo inventory through the protected custom Joomla endpoint."
    )
    parser.add_argument("article_id", type=int, help="Joomla article ID")
    parser.add_argument(
        "--env-file", type=Path, default=DEFAULT_ENV_FILE,
        help=f"Site and endpoint settings file (default: {DEFAULT_ENV_FILE}).",
    )
    parser.add_argument("--output", type=Path, help="Write JSON to this file instead of stdout.")
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
        endpoint = urlunsplit((site.scheme, site.netloc, "/ws/article-photos.php", "", ""))
        url = endpoint + "?" + urlencode({"id": args.article_id})
        inventory = get_json(url, settings["GRIMPEROOTS_WS_TOKEN"])
    except LookupError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    output = json.dumps(inventory, ensure_ascii=False, indent=2) + "\n"
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
