#!/usr/bin/env python3
"""Export a lightweight, read-only index of Joomla CRs through a temporary PHP bridge."""

from __future__ import annotations

import argparse
import ftplib
import hashlib
import io
import json
import secrets
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from fetch_article_from_db import (
    DEFAULT_ENV_FILE,
    REQUIRED_ENV_KEYS,
    bridge_url,
    create_ssl_context,
    load_settings,
    open_ftp,
)


DEFAULT_OUTPUT = Path("data/cr_index.json")
DEFAULT_CATEGORY_ID = 33
REQUEST_TIMEOUT = 30


def php_index_bridge_source(category_id: int, token_hash: str) -> bytes:
    """Create a one-time endpoint that returns only CR ID, title and date."""
    source = f'''<?php
declare(strict_types=1);
ini_set('display_errors', '0');
error_reporting(0);
header('Content-Type: application/json; charset=utf-8');

$provided = $_SERVER['HTTP_X_FETCH_TOKEN'] ?? '';
$expectedHash = '{token_hash}';
if ($provided === '' || !hash_equals($expectedHash, hash('sha256', $provided))) {{
    http_response_code(404);
    exit;
}}

try {{
    require_once __DIR__ . '/configuration.php';
    $config = new JConfig();
    $prefix = (string) $config->dbprefix;
    if (!preg_match('/^[A-Za-z0-9_]+$/', $prefix)) {{
        throw new RuntimeException('Invalid table prefix');
    }}

    $port = isset($config->port) ? (int) $config->port : 3306;
    $db = new mysqli($config->host, $config->user, $config->password, $config->db, $port);
    $db->set_charset('utf8mb4');

    $sql = 'SELECT c.id, c.title, c.created '
         . 'FROM `' . $prefix . 'content` AS c '
         . 'INNER JOIN `' . $prefix . 'categories` AS cat ON cat.id = c.catid '
         . 'INNER JOIN `' . $prefix . 'categories` AS root ON root.id = ? '
         . "WHERE cat.extension = 'com_content' "
         . 'AND cat.lft >= root.lft AND cat.rgt <= root.rgt '
         . 'AND c.state = 1 '
         . 'ORDER BY c.created DESC, c.id DESC';
    $stmt = $db->prepare($sql);
    $categoryId = {category_id};
    $stmt->bind_param('i', $categoryId);
    $stmt->execute();
    $stmt->bind_result($id, $title, $created);

    $articles = [];
    while ($stmt->fetch()) {{
        $articles[] = [
            'id' => (int) $id,
            'title' => $title,
            'created' => $created,
        ];
    }}
    $stmt->close();
    $db->close();

    echo json_encode(
        ['data' => $articles, 'meta' => ['count' => count($articles)]],
        JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES
    );
}} catch (Throwable $error) {{
    http_response_code(500);
    echo json_encode(['error' => 'CR index lookup failed']);
}}
'''
    return source.encode("utf-8")


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Do not forward the one-time access token to a redirected URL."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def request_index(url: str, token: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "X-Fetch-Token": token},
        method="GET",
    )
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=create_ssl_context()),
        NoRedirectHandler(),
    )
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"The temporary index bridge returned HTTP {error.code}.") from error
    except urllib.error.URLError as error:
        reason = error.reason
        if isinstance(reason, ssl.SSLCertVerificationError):
            detail = "TLS certificate verification failed"
        elif isinstance(reason, ssl.SSLError):
            detail = "TLS negotiation failed"
        else:
            detail = f"network error ({type(reason).__name__})"
        raise RuntimeError(f"Could not fetch the CR index through HTTPS: {detail}.") from error
    except (TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RuntimeError(f"Could not fetch the CR index ({type(error).__name__}).") from error

    if not isinstance(payload, dict):
        raise RuntimeError("The temporary bridge returned an unexpected JSON response.")
    if payload.get("error"):
        raise RuntimeError("The PHP bridge could not read the CR index; check Joomla's database configuration.")
    records = payload.get("data")
    if not isinstance(records, list):
        raise RuntimeError("The temporary bridge returned an unexpected CR index.")
    return payload


def fetch_cr_index(category_id: int, settings: dict[str, str]) -> dict:
    token = secrets.token_urlsafe(32)
    remote_filename = f"fetch-cr-index-{secrets.token_hex(16)}.php"
    url = bridge_url(settings["SITE_URL"], remote_filename)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    ftp: ftplib.FTP | None = None
    uploaded = False
    try:
        ftp = open_ftp(settings)
        ftp.storbinary(
            f"STOR {remote_filename}",
            io.BytesIO(php_index_bridge_source(category_id, token_hash)),
        )
        uploaded = True
        return request_index(url, token)
    finally:
        if ftp is not None:
            if uploaded:
                try:
                    ftp.delete(remote_filename)
                except ftplib.all_errors:
                    print(
                        "Warning: could not remove the temporary PHP bridge via FTP; "
                        "delete the remaining fetch-cr-index-*.php file from the Joomla root.",
                        file=sys.stderr,
                    )
            try:
                ftp.quit()
            except ftplib.all_errors:
                ftp.close()


def public_article_url(site_url: str, article_id: int) -> str:
    return f"{site_url.rstrip('/')}/{article_id}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export a lightweight index of published Joomla CRs through a read-only SQL bridge."
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help=f"FTP and site settings file (default: {DEFAULT_ENV_FILE}).",
    )
    parser.add_argument(
        "--category-id",
        type=int,
        default=DEFAULT_CATEGORY_ID,
        help=f"Root Joomla category whose descendants contain the CRs (default: {DEFAULT_CATEGORY_ID}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output JSON file (default: {DEFAULT_OUTPUT}).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Run the temporary read-only bridge on the hosting account.")
    mode.add_argument("--dry-run", action="store_true", help="Show the planned export without contacting the hosting account (default).")
    args = parser.parse_args()
    if args.category_id <= 0:
        parser.error("category-id must be a positive integer")

    try:
        settings = load_settings(args.env_file)
        missing = [key for key in REQUIRED_ENV_KEYS if not settings.get(key)]
        if missing:
            raise ValueError(
                "Missing setting(s): " + ", ".join(missing)
                + f". Set them in {args.env_file} or in the process environment."
            )
        site_parts = urlsplit(settings["SITE_URL"])
        if site_parts.scheme != "https" or not site_parts.netloc:
            raise ValueError("SITE_URL must be an https URL for the Joomla installation.")
        if not args.apply:
            print(
                f"Dry-run: would export published articles in category {args.category_id} "
                f"and its descendants to {args.output}, then remove the temporary PHP bridge."
            )
            return 0
        payload = fetch_cr_index(args.category_id, settings)
    except LookupError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except ftplib.all_errors as error:
        print(f"FTP operation failed ({type(error).__name__}); check FTP settings and access.", file=sys.stderr)
        return 1

    for article in payload["data"]:
        if not isinstance(article, dict) or article.get("id") is None:
            print("Error: the temporary bridge returned an invalid article record.", file=sys.stderr)
            return 1
        article["url"] = public_article_url(settings["SITE_URL"], int(article["id"]))

    output = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    except OSError as error:
        print(f"Could not write {args.output}: {error}", file=sys.stderr)
        return 1
    print(f"Exported {payload['meta']['count']} CRs to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
