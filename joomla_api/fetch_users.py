#!/usr/bin/env python3
"""Fetch Joomla user IDs, logins, names, groups, and account status."""

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
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


ENV_KEYS = ("JOOMLA_BASE_URL", "JOOMLA_TOKEN")
DEFAULT_OUTPUT = Path("data/users.json")
PAGE_SIZE = 100


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values

    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
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
            raise ValueError(f"Invalid value for {key} on line {line_number} of {path}") from error
        values[key] = parts[0] if parts else ""
    return values


def load_settings() -> dict[str, str]:
    settings: dict[str, str] = {}
    for filename in (".env", ".env.local"):
        settings.update(read_env_file(Path(filename)))
    settings.update({key: os.environ[key] for key in ENV_KEYS if os.environ.get(key)})
    return settings


def users_endpoint(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    path = urlsplit(base_url).path.rstrip("/")
    if path.endswith("/api/index.php/v1"):
        return f"{base_url}/users"
    if path.endswith("/api/index.php"):
        return f"{base_url}/v1/users"
    return f"{base_url}/api/index.php/v1/users"


def create_ssl_context() -> ssl.SSLContext:
    paths = ssl.get_default_verify_paths()
    candidates = (
        os.environ.get("SSL_CERT_FILE"),
        paths.cafile,
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/pki/tls/certs/ca-bundle.crt",
        "/etc/ssl/cert.pem",
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return ssl.create_default_context(cafile=candidate)
    if paths.capath and Path(paths.capath).is_dir():
        return ssl.create_default_context(capath=paths.capath)
    return ssl.create_default_context()


class NoRedirectHandler(HTTPRedirectHandler):
    """Do not forward the API token to a redirected destination."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def get_page(url: str, token: str, opener) -> dict:
    request = Request(
        url,
        headers={"Accept": "application/vnd.api+json", "X-Joomla-Token": token},
        method="GET",
    )
    try:
        with opener.open(request, timeout=30) as response:
            payload = json.loads(response.read())
    except HTTPError as error:
        print(f"Joomla returned HTTP {error.code} ({error.reason}) while fetching users.", file=sys.stderr)
        if error.code == 401:
            print("Check the token and API login permissions.", file=sys.stderr)
        elif error.code == 403:
            print("The token owner needs permission to read users (com_users).", file=sys.stderr)
        raise RuntimeError("Joomla API request failed") from error
    except URLError as error:
        reason = error.reason
        if isinstance(reason, ssl.SSLCertVerificationError):
            print("TLS certificate verification failed; certificate checks remain enabled.", file=sys.stderr)
        else:
            print(f"Could not reach Joomla: {type(reason).__name__}", file=sys.stderr)
        raise RuntimeError("Joomla API request failed") from error
    except (TimeoutError, json.JSONDecodeError) as error:
        print(f"Request failed: {type(error).__name__}", file=sys.stderr)
        raise RuntimeError("Joomla API request failed") from error

    if not isinstance(payload, dict):
        raise RuntimeError("Joomla returned an unexpected JSON response.")
    return payload


def group_names(attributes: dict) -> list[str]:
    raw_names = attributes.get("group_names")
    if isinstance(raw_names, str):
        return [name.strip() for name in raw_names.splitlines() if name.strip()]
    if isinstance(raw_names, list):
        return [name.strip() for name in raw_names if isinstance(name, str) and name.strip()]
    return []


def fetch_all_users(base_url: str, token: str) -> list[dict]:
    endpoint = users_endpoint(base_url)
    first_page = endpoint + "?" + urlencode({"page[limit]": PAGE_SIZE})
    allowed_origin = urlsplit(endpoint)[:2]
    next_url: str | None = first_page
    seen_pages: set[str] = set()
    seen_ids: set[str] = set()
    users: list[dict] = []
    ssl_context = create_ssl_context()
    opener = build_opener(HTTPSHandler(context=ssl_context), NoRedirectHandler())

    while next_url:
        parts = urlsplit(next_url)
        if parts[:2] != allowed_origin or parts.scheme != "https":
            raise RuntimeError("Joomla returned an unsafe pagination URL; refusing to send the token.")
        if next_url in seen_pages:
            raise RuntimeError("Joomla returned a pagination loop while fetching users.")
        seen_pages.add(next_url)

        payload = get_page(next_url, token, opener)
        resources = payload.get("data", payload)
        if not isinstance(resources, list):
            raise RuntimeError("Joomla returned an unexpected users collection.")

        for resource in resources:
            if not isinstance(resource, dict):
                raise RuntimeError("Joomla returned an unexpected user resource.")
            user_id = resource.get("id")
            attributes = resource.get("attributes", {})
            if not isinstance(attributes, dict):
                attributes = {}
            username = attributes.get("username")
            name = attributes.get("name")
            if user_id is None or not isinstance(username, str) or not isinstance(name, str):
                raise RuntimeError("Joomla returned a user without an ID, login, or name.")

            user_key = str(user_id)
            if user_key in seen_ids:
                continue
            seen_ids.add(user_key)
            users.append(
                {
                    "id": user_key,
                    "username": username,
                    "name": name,
                    "groups": group_names(attributes),
                    "blocked": str(attributes.get("block", 0)).casefold() not in {"0", "false", ""},
                }
            )

        links = payload.get("links", {})
        next_link = links.get("next") if isinstance(links, dict) else None
        next_url = urljoin(next_url, next_link) if isinstance(next_link, str) and next_link else None

    users.sort(key=lambda user: user["username"].casefold())
    return users


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List Joomla user IDs, logins, names, and assigned groups through the read-only API.",
        usage="%(prog)s [-h] [--superuser] [--output PATH]",
    )
    parser.add_argument(
        "--superuser",
        action="store_true",
        help="List only accounts belonging to the Joomla 'Super Users' group.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Save the selected user data (default: {DEFAULT_OUTPUT}).",
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
        print("Set JOOMLA_BASE_URL and JOOMLA_TOKEN in the environment, .env, or .env.local.", file=sys.stderr)
        return 2
    parsed_base = urlsplit(base_url)
    if parsed_base.scheme != "https" or not parsed_base.netloc:
        print("JOOMLA_BASE_URL must be an https URL.", file=sys.stderr)
        return 2

    try:
        all_users = fetch_all_users(base_url, token)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    except OSError as error:
        print(f"Could not read TLS configuration or complete request: {error}", file=sys.stderr)
        return 1

    users = [
        user for user in all_users
        if not args.superuser or "Super Users" in user["groups"]
    ]

    output = json.dumps(
        {"data": users, "meta": {"count": len(users)}},
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    except OSError as error:
        print(f"Could not write {args.output}: {error}", file=sys.stderr)
        return 1

    scope = "Super Users" if args.superuser else "users"
    print(f"Listed {len(users)} Joomla {scope}; saved {args.output}.")
    rows = [
        (
            user["id"],
            user["username"],
            user["name"],
            ", ".join(user["groups"]) or "(aucun groupe)",
            "bloqué" if user["blocked"] else "actif",
        )
        for user in users
    ]
    headers = ("ID", "LOGIN", "NOM", "GROUPES", "ÉTAT")
    widths = tuple(
        max([len(header), *(len(row[index]) for row in rows)])
        for index, header in enumerate(headers)
    )
    print(
        f"{headers[0]:>{widths[0]}}  {headers[1]:<{widths[1]}}  "
        f"{headers[2]:<{widths[2]}}  {headers[3]:<{widths[3]}}  {headers[4]}"
    )
    print(
        f"{'-' * widths[0]}  {'-' * widths[1]}  {'-' * widths[2]}  "
        f"{'-' * widths[3]}  {'-' * len(headers[4])}"
    )
    for row in rows:
        print(
            f"{row[0]:>{widths[0]}}  {row[1]:<{widths[1]}}  "
            f"{row[2]:<{widths[2]}}  {row[3]:<{widths[3]}}  {row[4]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
