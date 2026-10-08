#!/usr/bin/env python3
"""Fetch one Joomla article through a temporary, read-only PHP bridge over FTP."""

from __future__ import annotations

import argparse
import ftplib
import hashlib
import json
import os
import secrets
import shlex
import socket
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from typing import Any


ENV_KEYS = (
    "FTP_HOST",
    "FTP_USER",
    "FTP_PASSWORD",
    "FTP_PLAIN",
    "SITE_URL",
    "REMOTE_ROOT",
)
REQUIRED_ENV_KEYS = ("FTP_HOST", "FTP_USER", "FTP_PASSWORD", "SITE_URL", "REMOTE_ROOT")
DEFAULT_ENV_FILE = Path(".env.local")
REQUEST_TIMEOUT = 20


def read_env_file(path: Path) -> dict[str, str]:
    """Read the FTP and site settings from a dotenv-style file."""
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


def php_bridge_source(article_id: int, token_hash: str) -> bytes:
    """Create a PHP endpoint that only performs SELECT queries for this article."""
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

    $sql = 'SELECT c.id, c.title, c.alias, c.catid AS category_id, '
         . 'cat.title AS category, c.created, c.introtext, c.fulltext '
         . 'FROM `' . $prefix . 'content` AS c '
         . 'LEFT JOIN `' . $prefix . 'categories` AS cat ON cat.id = c.catid '
         . 'WHERE c.id = ? LIMIT 1';
    $stmt = $db->prepare($sql);
    $articleId = {article_id};
    $stmt->bind_param('i', $articleId);
    $stmt->execute();
    $stmt->bind_result($id, $title, $alias, $categoryId, $category, $created, $introtext, $fulltext);
    if (!$stmt->fetch()) {{
        echo json_encode(['error' => 'Article not found']);
        exit;
    }}
    $article = [
        'id' => (int) $id,
        'title' => $title,
        'alias' => $alias,
        'category_id' => (int) $categoryId,
        'category' => $category,
        'created' => $created,
        'introtext' => $introtext,
        'fulltext' => $fulltext,
        'existing_tags' => [],
    ];
    $stmt->close();

    $tagSql = 'SELECT tag_id FROM `' . $prefix . 'contentitem_tag_map` '
            . 'WHERE content_item_id = ? AND type_alias = ? ORDER BY tag_id';
    $tagStmt = $db->prepare($tagSql);
    $typeAlias = 'com_content.article';
    $tagStmt->bind_param('is', $articleId, $typeAlias);
    $tagStmt->execute();
    $tagStmt->bind_result($tagId);
    while ($tagStmt->fetch()) {{
        $article['existing_tags'][] = (int) $tagId;
    }}
    $tagStmt->close();
    $db->close();

    echo json_encode($article, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
}} catch (Throwable $error) {{
    http_response_code(500);
    echo json_encode(['error' => 'Article lookup failed']);
}}
'''
    return source.encode("utf-8")


def bridge_url(site_url: str, remote_filename: str) -> str:
    parts = urlsplit(site_url)
    if parts.scheme != "https" or not parts.netloc:
        raise ValueError("SITE_URL must be an https URL for the temporary bridge.")
    path = parts.path.rstrip("/") + "/" + remote_filename
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def create_ssl_context() -> ssl.SSLContext:
    """Use Python's configured CA file, or a standard OS certificate bundle."""
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


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep the one-time token on the configured origin only."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def request_article(url: str, token: str) -> dict[str, Any]:
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
        if error.code == 404:
            raise RuntimeError("The temporary bridge returned 404; check SITE_URL and REMOTE_ROOT.") from error
        raise RuntimeError(f"The temporary bridge returned HTTP {error.code}.") from error
    except urllib.error.URLError as error:
        reason = error.reason
        if isinstance(reason, ssl.SSLCertVerificationError):
            verify_message = getattr(reason, "verify_message", "certificate verification failed")
            verify_code = getattr(reason, "verify_code", "unknown")
            detail = f"TLS certificate verification failed ({verify_message}; code {verify_code})"
        elif isinstance(reason, ssl.SSLError):
            detail = "TLS negotiation failed"
        elif isinstance(reason, socket.gaierror):
            detail = f"DNS lookup failed (socket error {reason.errno})"
        elif isinstance(reason, (TimeoutError, socket.timeout)):
            detail = "HTTPS connection timed out"
        elif isinstance(reason, OSError):
            detail = f"network error ({type(reason).__name__}, errno {reason.errno})"
        else:
            detail = f"network error ({type(reason).__name__})"
        raise RuntimeError(f"Could not fetch the article through the HTTPS bridge: {detail}.") from error
    except (TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RuntimeError(f"Could not fetch the article through the HTTPS bridge ({type(error).__name__}).") from error

    if not isinstance(payload, dict):
        raise RuntimeError("The temporary bridge returned an unexpected JSON response.")
    if payload.get("error") == "Article not found":
        raise LookupError("Article not found.")
    if payload.get("error"):
        raise RuntimeError("The PHP bridge could not read the article; check Joomla's database configuration and schema.")
    return payload


def open_ftp(settings: dict[str, str]) -> ftplib.FTP:
    plain = settings.get("FTP_PLAIN", "").strip().lower() in {"1", "true", "yes", "on"}
    if plain:
        ftp: ftplib.FTP = ftplib.FTP(timeout=REQUEST_TIMEOUT)
    else:
        ftp = ftplib.FTP_TLS(context=ssl.create_default_context(), timeout=REQUEST_TIMEOUT)
    ftp.connect(settings["FTP_HOST"], 21, timeout=REQUEST_TIMEOUT)
    ftp.login(settings["FTP_USER"], settings["FTP_PASSWORD"])
    if isinstance(ftp, ftplib.FTP_TLS):
        ftp.prot_p()
    ftp.cwd(settings["REMOTE_ROOT"])
    return ftp


def fetch_via_ftp_bridge(article_id: int, settings: dict[str, str]) -> dict[str, Any]:
    token = secrets.token_urlsafe(32)
    remote_filename = f"fetch-article-{secrets.token_hex(16)}.php"
    url = bridge_url(settings["SITE_URL"], remote_filename)
    ftp: ftplib.FTP | None = None
    uploaded = False
    try:
        ftp = open_ftp(settings)
        import io

        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        ftp.storbinary(
            f"STOR {remote_filename}",
            io.BytesIO(php_bridge_source(article_id, token_hash)),
        )
        uploaded = True
        # Only the token hash is uploaded; the one-time token goes over HTTPS.
        return request_article(url, token)
    finally:
        if ftp is not None:
            if uploaded:
                try:
                    ftp.delete(remote_filename)
                except ftplib.all_errors as error:
                    print(
                        "Warning: could not remove the temporary PHP bridge via FTP; "
                        "delete it from the hosting root manually.",
                        file=sys.stderr,
                    )
            try:
                ftp.quit()
            except ftplib.all_errors:
                ftp.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch one Joomla article using a temporary read-only PHP bridge over FTP."
    )
    parser.add_argument("article_id", type=int, help="Joomla article ID")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help=f"FTP and site settings file (default: {DEFAULT_ENV_FILE}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON to this file instead of stdout.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Upload and remove the temporary PHP bridge on the hosting account.",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the planned retrieval without contacting the hosting account (default).",
    )
    args = parser.parse_args()
    if args.article_id <= 0:
        parser.error("article_id must be a positive integer")

    try:
        settings = load_settings(args.env_file)
        missing = [key for key in REQUIRED_ENV_KEYS if not settings.get(key)]
        if missing:
            raise ValueError(
                "Missing setting(s): " + ", ".join(missing)
                + f". Set them in {args.env_file} or in the process environment."
            )
        if not args.apply:
            print(
                f"Dry-run: would upload a temporary PHP reader for article {args.article_id}, "
                "fetch its JSON over HTTPS, then remove the PHP file. "
                "Use --apply to perform this FTP operation."
            )
            return 0
        article = fetch_via_ftp_bridge(args.article_id, settings)
    except LookupError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except ftplib.all_errors as error:
        print(f"FTP operation failed ({type(error).__name__}); check FTP settings and access.", file=sys.stderr)
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
