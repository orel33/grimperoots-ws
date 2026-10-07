#!/usr/bin/env python3
"""Fetch Joomla content articles through the read-only Web Services API."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import ssl
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen


ENV_KEYS = ("JOOMLA_BASE_URL", "JOOMLA_TOKEN")
DEFAULT_OUTPUT = Path("data/articles.json")
PAGE_SIZE = 100


def read_env_file(path: Path) -> dict[str, str]:
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
    settings: dict[str, str] = {}
    for filename in (".env", ".env.local"):
        settings.update(read_env_file(Path(filename)))
    settings.update({key: os.environ[key] for key in ENV_KEYS if os.environ.get(key)})
    return settings


def articles_endpoint(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    path = urlsplit(base_url).path.rstrip("/")
    if path.endswith("/api/index.php/v1"):
        return f"{base_url}/content/articles"
    if path.endswith("/api/index.php"):
        return f"{base_url}/v1/content/articles"
    return f"{base_url}/api/index.php/v1/content/articles"


def create_ssl_context() -> ssl.SSLContext:
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


def get_page(url: str, token: str, ssl_context: ssl.SSLContext) -> dict:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.api+json",
            "X-Joomla-Token": token,
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=30, context=ssl_context) as response:
            payload = json.loads(response.read())
    except HTTPError as error:
        print(
            f"Joomla returned HTTP {error.code} ({error.reason}) while fetching articles.",
            file=sys.stderr,
        )
        if error.code == 401:
            print("Check the token and API login permissions.", file=sys.stderr)
        raise RuntimeError("Joomla API request failed") from error
    except URLError as error:
        reason = error.reason
        if isinstance(reason, ssl.SSLCertVerificationError):
            print(
                "TLS certificate verification failed. Check the local CA trust; "
                "certificate verification remains enabled.",
                file=sys.stderr,
            )
        else:
            print(f"Could not reach Joomla: {reason}", file=sys.stderr)
        raise RuntimeError("Joomla API request failed") from error
    except (TimeoutError, json.JSONDecodeError) as error:
        print(f"Request failed: {error}", file=sys.stderr)
        raise RuntimeError("Joomla API request failed") from error

    if not isinstance(payload, dict):
        raise RuntimeError("Joomla returned an unexpected JSON shape.")
    return payload


def fetch_all_articles(base_url: str, token: str) -> list[dict]:
    endpoint = articles_endpoint(base_url)
    first_page = endpoint + "?" + urlencode({"page[limit]": PAGE_SIZE})
    allowed_origin = urlsplit(endpoint)[:2]
    next_url: str | None = first_page
    seen_pages: set[str] = set()
    seen_ids: set[str] = set()
    articles: list[dict] = []
    ssl_context = create_ssl_context()

    while next_url:
        parts = urlsplit(next_url)
        if parts[:2] != allowed_origin or parts.scheme != "https":
            raise RuntimeError(
                "Joomla returned an unsafe pagination URL; refusing to send the token."
            )
        if next_url in seen_pages:
            raise RuntimeError("Joomla returned a pagination loop while fetching articles.")
        seen_pages.add(next_url)

        payload = get_page(next_url, token, ssl_context)
        resources = payload.get("data", payload)
        if not isinstance(resources, list):
            raise RuntimeError("Joomla returned an unexpected articles collection.")

        for resource in resources:
            if not isinstance(resource, dict):
                raise RuntimeError("Joomla returned an unexpected article resource.")
            article_id = resource.get("id")
            if article_id is None:
                raise RuntimeError("Joomla returned an article without an ID.")
            article_key = str(article_id)
            if article_key not in seen_ids:
                seen_ids.add(article_key)
                articles.append(resource)

        links = payload.get("links", {})
        next_link = links.get("next") if isinstance(links, dict) else None
        next_url = urljoin(next_url, next_link) if isinstance(next_link, str) and next_link else None

    return articles


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch all Joomla content articles through the read-only API."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Save the articles JSON response (default: {DEFAULT_OUTPUT}).",
    )
    args = parser.parse_args()

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
    if parsed_base.scheme != "https" or not parsed_base.netloc:
        print("JOOMLA_BASE_URL must be an https URL.", file=sys.stderr)
        return 2

    try:
        articles = fetch_all_articles(base_url, token)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    except OSError as error:
        print(f"Could not read TLS configuration or complete request: {error}", file=sys.stderr)
        return 1

    output = json.dumps(
        {"data": articles, "meta": {"count": len(articles)}},
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    except OSError as error:
        print(f"Could not write {args.output}: {error}", file=sys.stderr)
        return 1

    print(f"Fetched {len(articles)} Joomla articles; saved {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
