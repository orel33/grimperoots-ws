#!/usr/bin/env python3
"""Demonstrate creating an unpublished Joomla article through the Web Services API."""

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


def articles_endpoint(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    path = urlsplit(base_url).path.rstrip("/")
    if path.endswith("/api/index.php/v1"):
        return f"{base_url}/content/articles"
    if path.endswith("/api/index.php"):
        return f"{base_url}/v1/content/articles"
    return f"{base_url}/api/index.php/v1/content/articles"


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
    """Never forward the Joomla token to a redirect target."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def safe_endpoint(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("JOOMLA_BASE_URL must be an HTTPS URL without credentials, query, or fragment.")
    return articles_endpoint(base_url)


def error_summary(error: HTTPError) -> str:
    try:
        payload = json.loads(error.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    errors = payload.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        detail = errors[0].get("detail") or errors[0].get("title")
        if isinstance(detail, str):
            return detail[:400]
    return ""


def post_article(endpoint: str, token: str, article: dict) -> dict:
    request = Request(
        endpoint,
        data=json.dumps(article, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/json",
            "X-Joomla-Token": token,
        },
        method="POST",
    )
    opener = build_opener(
        HTTPSHandler(context=create_ssl_context()),
        NoRedirectHandler(),
    )
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error_summary(error)
        message = f"Joomla API returned HTTP {error.code} ({error.reason})."
        if error.code == 401:
            message += " Check JOOMLA_TOKEN and the account's API login permission."
        elif error.code == 403:
            message += " Check the account's permission to create content articles in this category."
        if detail:
            message += f" Joomla says: {detail}"
        raise RuntimeError(message) from error
    except URLError as error:
        reason = error.reason
        if isinstance(reason, ssl.SSLCertVerificationError):
            message = "TLS certificate verification failed; certificate checks remain enabled."
        elif isinstance(reason, ssl.SSLError):
            message = "TLS negotiation failed."
        else:
            message = f"Could not reach Joomla ({type(reason).__name__})."
        raise RuntimeError(message) from error
    except (TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Invalid or timed-out Joomla response ({type(error).__name__}).") from error

    if not isinstance(payload, dict):
        raise RuntimeError("Joomla returned an unexpected JSON response.")
    return payload


def find_author_id(base_url: str, login: str, token: str) -> int:
    """Resolve an exact Joomla login through the read-only Users API."""
    endpoint = users_endpoint(base_url)
    first_url = endpoint + "?" + urlencode({"filter[search]": login, "page[limit]": 100})
    allowed_origin = urlsplit(endpoint)[:2]
    next_url: str | None = first_url
    seen_urls: set[str] = set()
    matches: dict[str, int] = {}
    opener = build_opener(
        HTTPSHandler(context=create_ssl_context()),
        NoRedirectHandler(),
    )

    while next_url:
        parsed = urlsplit(next_url)
        if parsed.scheme != "https" or parsed[:2] != allowed_origin:
            raise RuntimeError("Joomla returned an unsafe user lookup URL; refusing to send the token.")
        if next_url in seen_urls:
            raise RuntimeError("Joomla returned a pagination loop while looking up the author.")
        seen_urls.add(next_url)
        request = Request(
            next_url,
            headers={"Accept": "application/vnd.api+json", "X-Joomla-Token": token},
            method="GET",
        )
        try:
            with opener.open(request, timeout=TIMEOUT) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error_summary(error)
            message = f"Joomla API returned HTTP {error.code} while looking up users."
            if error.code == 401:
                message += " Check JOOMLA_TOKEN and the account's API login permission."
            elif error.code == 403:
                message += " The token owner needs permission to read users for --login lookup."
            if detail:
                message += f" Joomla says: {detail}"
            raise RuntimeError(message) from error
        except URLError as error:
            reason = error.reason
            if isinstance(reason, ssl.SSLCertVerificationError):
                message = "TLS certificate verification failed; certificate checks remain enabled."
            elif isinstance(reason, ssl.SSLError):
                message = "TLS negotiation failed."
            else:
                message = f"Could not reach Joomla ({type(reason).__name__})."
            raise RuntimeError(message) from error
        except (TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Invalid or timed-out Joomla response ({type(error).__name__}).") from error

        if not isinstance(payload, dict):
            raise RuntimeError("Joomla returned an unexpected user lookup response.")
        resources = payload.get("data", payload)
        if not isinstance(resources, list):
            raise RuntimeError("Joomla returned an unexpected users collection.")
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            attributes = resource.get("attributes", {})
            username = attributes.get("username") if isinstance(attributes, dict) else None
            user_id = resource.get("id")
            if isinstance(username, str) and username.casefold() == login.casefold() and user_id is not None:
                try:
                    matches[str(user_id)] = int(user_id)
                except (TypeError, ValueError) as error:
                    raise RuntimeError("Joomla returned a non-numeric user ID for the requested login.") from error

        links = payload.get("links", {})
        next_link = links.get("next") if isinstance(links, dict) else None
        next_url = urljoin(next_url, next_link) if isinstance(next_link, str) and next_link else None

    if not matches:
        raise RuntimeError(f"No Joomla user exactly matches login '{login}'.")
    if len(matches) > 1:
        raise RuntimeError(f"More than one Joomla user matched login '{login}'; refusing to choose an author.")
    return next(iter(matches.values()))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Demonstrate creating an unpublished article through Joomla Web Services."
    )
    parser.add_argument("--title", required=True, help="Title of the new draft article.")
    parser.add_argument("--category-id", required=True, type=int, help="Joomla category ID.")
    parser.add_argument("--text", required=True, help="Full article text (sent as articletext).")
    parser.add_argument("--login", help="Joomla login to set as the article author (created_by).")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--dry-run", action="store_true", help="Preview only (the default).")
    action.add_argument("--apply", action="store_true", help="Create an unpublished article in Joomla.")
    args = parser.parse_args()

    title = args.title.strip()
    if not title or not args.text.strip():
        parser.error("--title and --text must not be empty.")
    if args.category_id < 1:
        parser.error("--category-id must be a positive integer.")

    try:
        settings = load_settings(args.env_file)
        base_url = settings.get("JOOMLA_BASE_URL", "").strip()
        if not base_url:
            raise ValueError(f"Set JOOMLA_BASE_URL in the environment or {args.env_file}.")
        endpoint = safe_endpoint(base_url)
    except (OSError, ValueError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2

    article = {
        "title": title,
        "catid": args.category_id,
        "articletext": args.text,
        "language": "*",
        "state": 0,
    }
    author_id = None
    token = settings.get("JOOMLA_TOKEN", "").strip()
    if args.login is not None:
        login = args.login.strip()
        if not login:
            parser.error("--login must not be empty.")
        if not token:
            print("Set JOOMLA_TOKEN to look up the author specified by --login.", file=sys.stderr)
            return 2
        try:
            author_id = find_author_id(base_url, login, token)
        except (RuntimeError, OSError) as error:
            print(f"Author lookup failed: {error}", file=sys.stderr)
            return 1
        article["created_by"] = author_id
        print(f"Resolved author login '{login}' to Joomla user ID {author_id}.")

    print(f"POST {endpoint}")
    print(json.dumps(article, ensure_ascii=False, indent=2))

    if not args.apply:
        if args.login is not None:
            print("Simulation : le login a été résolu par lecture, aucun POST de création n'a été envoyé.")
        else:
            print("Simulation uniquement : aucun appel n'a été envoyé à Joomla.")
        print("Ajoute --apply pour créer ce nouvel article non publié.")
        return 0

    if not token:
        print("Set JOOMLA_TOKEN in the environment or configuration file before using --apply.", file=sys.stderr)
        return 2

    try:
        response = post_article(endpoint, token, article)
    except RuntimeError as error:
        print(f"Article creation failed: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"Could not read TLS configuration or complete request: {error}", file=sys.stderr)
        return 1

    resource = response.get("data")
    article_id = resource.get("id") if isinstance(resource, dict) else None
    if article_id is None:
        print("Joomla accepted the request but returned no article ID.")
    else:
        message = f"Created unpublished Joomla article {article_id}."
        if args.login is not None:
            message += f" Requested author: {args.login.strip()} (user ID {author_id})."
            if isinstance(resource, dict) and isinstance(resource.get("attributes"), dict):
                actual_author_id = resource["attributes"].get("created_by")
                if actual_author_id is not None and str(actual_author_id) != str(author_id):
                    message += f" Joomla reports created_by={actual_author_id}; check the saved author in administration."
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
