#!/usr/bin/env python3
"""Demonstrate Joomla API authentication with an existing account over HTTPS."""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import shlex
import ssl
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


ENV_KEYS = ("JOOMLA_BASE_URL",)
DEFAULT_ENV_FILE = Path(".env.local")
TIMEOUT = 30


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


def load_settings(env_file: Path) -> dict[str, str]:
    settings: dict[str, str] = {}
    for path in (Path(".env"), env_file):
        settings.update(read_env_file(path))
    settings.update({key: os.environ[key] for key in ENV_KEYS if os.environ.get(key)})
    return settings


class NoRedirectHandler(HTTPRedirectHandler):
    """Do not forward HTTP Basic credentials to a redirected destination."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


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


def prompt_credentials() -> tuple[str, str]:
    if not sys.stdin.isatty():
        raise ValueError("Run this command in an interactive terminal to enter Joomla credentials.")
    username = input("Login Joomla : ").strip()
    password = getpass.getpass("Mot de passe Joomla : ")
    if not username or not password:
        raise ValueError("Login and password must not be empty.")
    if ":" in username:
        raise ValueError("A Joomla username used with HTTP Basic must not contain a colon.")
    return username, password


def request_users(base_url: str, username: str, password: str) -> int:
    endpoint = users_endpoint(base_url)
    parsed = urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("JOOMLA_BASE_URL must use HTTPS; refusing to send Basic credentials over HTTP.")

    url = endpoint + "?" + urlencode({"page[limit]": 1})
    encoded_credentials = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.api+json",
            "Authorization": f"Basic {encoded_credentials}",
        },
        method="GET",
    )
    opener = build_opener(
        HTTPSHandler(context=create_ssl_context()),
        NoRedirectHandler(),
    )
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code == 401:
            raise RuntimeError(
                "HTTP 401: Joomla rejected Basic authentication. Check that the "
                "'API Authentication - Basic' plugin is installed and enabled, and that the account credentials are correct."
            ) from error
        if error.code == 403:
            raise RuntimeError(
                "HTTP 403: Joomla denied access to the users endpoint. Check the account's API login "
                "and component permissions."
            ) from error
        raise RuntimeError(
            f"Joomla API returned HTTP {error.code}; check the API URL and account permissions."
        ) from error
    except URLError as error:
        reason = error.reason
        if isinstance(reason, ssl.SSLCertVerificationError):
            detail = "TLS certificate verification failed"
        elif isinstance(reason, ssl.SSLError):
            detail = "TLS negotiation failed"
        else:
            detail = f"network error ({type(reason).__name__})"
        raise RuntimeError(f"Could not contact the Joomla API: {detail}.") from error
    except (TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Invalid or timed-out response from Joomla ({type(error).__name__}).") from error

    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise RuntimeError("Joomla API returned an unexpected users response.")
    return len(payload["data"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Make a read-only Joomla API request using HTTP Basic authentication."
    )
    parser.add_argument(
        "--env-file", type=Path, default=DEFAULT_ENV_FILE,
        help=f"Settings file for JOOMLA_BASE_URL (default: {DEFAULT_ENV_FILE}).",
    )
    args = parser.parse_args()

    try:
        settings = load_settings(args.env_file)
        base_url = settings.get("JOOMLA_BASE_URL", "").strip()
        if not base_url:
            raise ValueError(f"Set JOOMLA_BASE_URL in the environment or {args.env_file}.")
        username, password = prompt_credentials()
        count = request_users(base_url, username, password)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Basic-auth demo failed: {error}", file=sys.stderr)
        return 1

    print("HTTP Basic authentication accepted by Joomla.")
    print("Endpoint: GET /api/index.php/v1/users?page[limit]=1")
    print(f"Records returned: {count} (response details omitted to avoid printing user data).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
