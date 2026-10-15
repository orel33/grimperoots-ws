"""Shared HTTPS client for the custom, read-only Joomla endpoints."""

from __future__ import annotations

import json
import os
import shlex
import socket
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ENV_KEYS = ("SITE_URL", "GRIMPEROOTS_WS_TOKEN")
REQUEST_TIMEOUT = 30


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
    settings = read_env_file(env_file)
    settings.update({key: os.environ[key] for key in ENV_KEYS if os.environ.get(key)})
    return settings


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


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never forward the shared endpoint token to a redirected URL."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def get_json(url: str, token: str | None = None) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["X-Grimperoots-Token"] = token
    request = urllib.request.Request(url, headers=headers, method="GET")
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=create_ssl_context()),
        NoRedirectHandler(),
    )
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise RuntimeError("Custom Joomla endpoint rejected the token (HTTP 401).") from error
        raise RuntimeError(f"Custom Joomla endpoint returned HTTP {error.code}.") from error
    except urllib.error.URLError as error:
        reason = error.reason
        if isinstance(reason, ssl.SSLCertVerificationError):
            detail = "TLS certificate verification failed"
        elif isinstance(reason, ssl.SSLError):
            detail = "TLS negotiation failed"
        elif isinstance(reason, socket.gaierror):
            detail = "DNS lookup failed"
        elif isinstance(reason, (TimeoutError, socket.timeout)):
            detail = "HTTPS connection timed out"
        else:
            detail = f"network error ({type(reason).__name__})"
        raise RuntimeError(f"Could not contact custom Joomla endpoint: {detail}.") from error
    except (TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RuntimeError(f"Invalid response from custom Joomla endpoint ({type(error).__name__}).") from error
    if not isinstance(payload, dict):
        raise RuntimeError("Custom Joomla endpoint returned an unexpected JSON response.")
    if payload.get("error"):
        message = payload["error"]
        if message == "Article not found":
            raise LookupError(message)
        raise RuntimeError(f"Custom Joomla endpoint error: {message}.")
    return payload
