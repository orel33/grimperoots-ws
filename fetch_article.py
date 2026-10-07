#!/usr/bin/env python3
"""Fetch one Joomla article through the read-only Web Services API."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import ssl
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


ENV_KEYS = ("JOOMLA_BASE_URL", "JOOMLA_TOKEN")


def read_env_file(path: Path) -> dict[str, str]:
    """Read the Joomla settings from a small dotenv-style file."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, raw_value = line.partition("=")
        key = key.strip()
        if not separator or key not in ENV_KEYS:
            continue
        try:
            parts = shlex.split(raw_value, comments=True, posix=True)
        except ValueError as error:
            raise ValueError(f"Invalid value for {key} in {path}") from error
        values[key] = parts[0] if parts else ""
    return values


def load_settings() -> dict[str, str]:
    """Load .env, then .env.local, with the process environment taking priority."""
    settings: dict[str, str] = {}
    for filename in (".env", ".env.local"):
        settings.update(read_env_file(Path(filename)))
    settings.update({key: os.environ[key] for key in ENV_KEYS if os.environ.get(key)})
    return settings


def article_endpoint(base_url: str, article_id: int) -> str:
    base_url = base_url.rstrip("/")
    path = urlsplit(base_url).path.rstrip("/")
    if path.endswith("/api/index.php/v1"):
        return f"{base_url}/content/articles/{article_id}"
    if path.endswith("/api/index.php"):
        return f"{base_url}/v1/content/articles/{article_id}"
    return f"{base_url}/api/index.php/v1/content/articles/{article_id}"


def create_ssl_context() -> ssl.SSLContext:
    """Use Python's configured CA file, or a standard OS bundle if it is missing."""
    default_paths = ssl.get_default_verify_paths()
    candidates = (
        os.environ.get("SSL_CERT_FILE"),
        default_paths.cafile,
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/pki/tls/certs/ca-bundle.crt",
        "/etc/ssl/cert.pem",
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return ssl.create_default_context(cafile=candidate)
    if default_paths.capath and Path(default_paths.capath).is_dir():
        return ssl.create_default_context(capath=default_paths.capath)
    return ssl.create_default_context()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch a Joomla article by ID using the Web Services API."
    )
    parser.add_argument("article_id", type=int, nargs="?", default=22)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data"),
        help="Save the raw Joomla JSON response here as <id>.json (default: data/).",
    )
    args = parser.parse_args()
    if args.article_id < 1:
        parser.error("article_id must be a positive integer")

    try:
        settings = load_settings()
    except (OSError, ValueError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2

    base_url = settings.get("JOOMLA_BASE_URL", "").strip()
    token = settings.get("JOOMLA_TOKEN", "").strip()
    if not base_url or not token:
        print(
            "Set JOOMLA_BASE_URL and JOOMLA_TOKEN in the environment, .env, or .env.local.",
            file=sys.stderr,
        )
        return 2

    parsed_base = urlsplit(base_url)
    if parsed_base.scheme not in ("http", "https") or not parsed_base.netloc:
        print("JOOMLA_BASE_URL must be an http(s) URL.", file=sys.stderr)
        return 2
    if parsed_base.scheme != "https":
        print("Refusing to send the Joomla token over plain HTTP.", file=sys.stderr)
        return 2

    url = article_endpoint(base_url, args.article_id)
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.api+json",
            "X-Joomla-Token": token,
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=30, context=create_ssl_context()) as response:
            status = response.status
            payload = json.loads(response.read())
    except HTTPError as error:
        print(
            f"Joomla returned HTTP {error.code} ({error.reason}) for article {args.article_id}.",
            file=sys.stderr,
        )
        if error.code == 401:
            print("Check the token and API login permissions.", file=sys.stderr)
        return 1
    except URLError as error:
        reason = error.reason
        if isinstance(reason, ssl.SSLCertVerificationError):
            print(
                "TLS certificate verification failed. Fix the server certificate or local CA trust; "
                "certificate verification remains enabled.",
                file=sys.stderr,
            )
        else:
            print(f"Could not reach Joomla: {reason}", file=sys.stderr)
        return 1
    except (TimeoutError, json.JSONDecodeError) as error:
        print(f"Request failed: {error}", file=sys.stderr)
        return 1

    if not isinstance(payload, dict):
        print("Joomla returned an unexpected JSON shape.", file=sys.stderr)
        return 1
    resource = payload.get("data", payload)
    if isinstance(resource, list):
        resource = resource[0] if resource else {}
    if not isinstance(resource, dict):
        print("Joomla returned an unexpected article resource.", file=sys.stderr)
        return 1
    attributes = resource.get("attributes", resource)
    if not isinstance(attributes, dict):
        attributes = {}
    returned_id = attributes.get("id", resource.get("id"))
    if str(returned_id) != str(args.article_id):
        print(
            f"Expected article {args.article_id}, but Joomla returned {returned_id!r}.",
            file=sys.stderr,
        )
        return 1

    output = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    json_path = args.output_dir / f"{args.article_id}.json"
    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        json_path.write_text(output, encoding="utf-8")
    except OSError as error:
        print(f"Could not write {json_path}: {error}", file=sys.stderr)
        return 1
    print(
        f"HTTP {status}: fetched article {args.article_id} "
        f"(title: {attributes.get('title', '(title unavailable)')}); saved {json_path}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
