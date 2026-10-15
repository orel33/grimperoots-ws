#!/usr/bin/env python3
"""Deploy one versioned custom Joomla WS endpoint to the OVH hosting."""

from __future__ import annotations

import argparse
import ftplib
import hashlib
import io
import json
import os
import posixpath
import re
import secrets
import shlex
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

from joomla_custom.ws_client import NoRedirectHandler, create_ssl_context


ROOT = Path(__file__).resolve().parent
WS_SOURCE_DIR = ROOT / "www" / "ws"
DEFAULT_ENV_FILE = Path(".env.local")
ENV_KEYS = (
    "FTP_HOST", "FTP_USER", "FTP_PASSWORD", "FTP_PLAIN", "REMOTE_ROOT",
    "SITE_URL", "GRIMPEROOTS_WS_TOKEN",
)
REQUIRED_KEYS = ("FTP_HOST", "FTP_USER", "FTP_PASSWORD", "REMOTE_ROOT")
TOKEN_REQUIRED_KEYS = (*REQUIRED_KEYS, "SITE_URL")
TIMEOUT = 30
TOKEN_CONSTANT = "GRIMPEROOTS_WS_TOKEN"


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
    values.update({key: os.environ[key] for key in ENV_KEYS if os.environ.get(key)})
    return values


def open_ftp(settings: dict[str, str]) -> ftplib.FTP:
    plain = settings.get("FTP_PLAIN", "").strip().lower() in {"1", "true", "yes", "on"}
    ftp: ftplib.FTP
    if plain:
        ftp = ftplib.FTP(timeout=TIMEOUT)
    else:
        ftp = ftplib.FTP_TLS(context=ssl.create_default_context(), timeout=TIMEOUT)
    ftp.connect(settings["FTP_HOST"], 21, timeout=TIMEOUT)
    ftp.login(settings["FTP_USER"], settings["FTP_PASSWORD"])
    if isinstance(ftp, ftplib.FTP_TLS):
        ftp.prot_p()
    return ftp


def deploy(filename: str, env_file: Path, apply: bool, overwrite: bool) -> int:
    if (
        Path(filename).name != filename
        or not filename.endswith(".php")
        or filename.startswith("_")
        or filename == "config.local.php"
    ):
        raise ValueError("Choose a versioned endpoint PHP file by its filename.")
    source = WS_SOURCE_DIR / filename
    if not source.is_file():
        raise ValueError(f"No versioned endpoint found at {source}.")

    settings = read_env_file(env_file)
    missing = [key for key in REQUIRED_KEYS if not settings.get(key)]
    if missing:
        raise ValueError(
            "Missing setting(s): " + ", ".join(missing)
            + f". Set them in {env_file} or in the process environment."
        )

    remote_root = settings["REMOTE_ROOT"].rstrip("/") or "/"
    remote_dir = posixpath.normpath(posixpath.join(remote_root, "..", "ws"))
    remote_path = posixpath.join(remote_dir, filename)
    source_bytes = source.read_bytes()
    print(f"Endpoint : {filename}")
    print(f"Destination : {remote_path}")
    print(f"Taille : {len(source_bytes)} octets")
    if not apply:
        print("Dry-run : aucun fichier envoyé. Relancer avec --apply pour déployer.")
        return 0

    ftp: ftplib.FTP | None = None
    try:
        ftp = open_ftp(settings)
        ftp.cwd(remote_dir)
        try:
            existing_size = ftp.size(filename)
        except ftplib.error_perm as error:
            if not str(error).startswith("550"):
                raise
            existing_size = None
        if existing_size is not None and not overwrite:
            raise FileExistsError(
                f"{remote_path} already exists; pass --overwrite to replace it."
            )

        ftp.storbinary(f"STOR {filename}", io.BytesIO(source_bytes))
        downloaded = io.BytesIO()
        ftp.retrbinary(f"RETR {filename}", downloaded.write)
        local_hash = hashlib.sha256(source_bytes).hexdigest()
        remote_hash = hashlib.sha256(downloaded.getvalue()).hexdigest()
        if local_hash != remote_hash:
            raise RuntimeError("The uploaded file differs from the local source.")
        print(f"Déployé et vérifié : {remote_path}")
    finally:
        if ftp is not None:
            try:
                ftp.quit()
            except ftplib.all_errors:
                ftp.close()
    return 0


def update_env_token_text(original: str, token: str) -> str:
    lines = original.splitlines(keepends=True)
    pattern = re.compile(r"^(\s*(?:export\s+)?GRIMPEROOTS_WS_TOKEN\s*=).*$")
    matches = [index for index, line in enumerate(lines) if pattern.match(line.rstrip("\r\n"))]
    if len(matches) > 1:
        raise ValueError(".env.local contains more than one GRIMPEROOTS_WS_TOKEN entry.")
    if matches:
        index = matches[0]
        ending = "\r\n" if lines[index].endswith("\r\n") else "\n" if lines[index].endswith("\n") else ""
        prefix = pattern.match(lines[index].rstrip("\r\n")).group(1)
        lines[index] = prefix + token + ending
        return "".join(lines)

    separator = "" if not original or original.endswith(("\n", "\r")) else "\n"
    return original + separator + f"GRIMPEROOTS_WS_TOKEN={token}\n"


def update_remote_config_text(original: str, token: str) -> str:
    definition = f"define('{TOKEN_CONSTANT}', '{token}');"
    pattern = re.compile(
        r"define\s*\(\s*(['\"])GRIMPEROOTS_WS_TOKEN\1\s*,\s*(['\"])(?:\\.|.)*?\2\s*\)\s*;",
        re.IGNORECASE | re.DOTALL,
    )
    matches = list(pattern.finditer(original))
    if len(matches) > 1:
        raise ValueError("Remote config.local.php defines the WS token more than once.")
    if matches:
        match = matches[0]
        return original[:match.start()] + definition + original[match.end():]
    if TOKEN_CONSTANT in original:
        raise ValueError("Could not safely identify the token definition in remote config.local.php.")

    open_tag = re.search(r"<\?php\b", original, re.IGNORECASE)
    if open_tag is None:
        raise ValueError("Remote config.local.php is not a PHP file.")
    insert_at = open_tag.end()
    return original[:insert_at] + "\n" + definition + original[insert_at:]


def replace_env_file(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".token-tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def ftp_read_file(ftp: ftplib.FTP, filename: str) -> bytes:
    content = io.BytesIO()
    ftp.retrbinary(f"RETR {filename}", content.write)
    return content.getvalue()


def verify_new_token(site_url: str, token: str) -> None:
    site = urlsplit(site_url)
    if site.scheme != "https" or not site.netloc:
        raise ValueError("SITE_URL must be an https URL to verify the new token.")
    endpoint = urlunsplit((site.scheme, site.netloc, "/ws/article.php", "", ""))
    url = endpoint + "?" + urlencode({"id": 0})
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "X-Grimperoots-Token": token},
        method="GET",
    )
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=create_ssl_context()),
        NoRedirectHandler(),
    )
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            body = response.read()
            raise RuntimeError(f"Token verification returned unexpected HTTP {response.status}.")
    except urllib.error.HTTPError as error:
        body = error.read()
        if error.code != 400:
            raise RuntimeError(f"Token verification returned HTTP {error.code}.") from error
    except urllib.error.URLError as error:
        raise RuntimeError("Could not verify the new token over HTTPS.") from error

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("The token verification endpoint returned invalid JSON.") from error
    if payload.get("error") != "Invalid id":
        raise RuntimeError("The WS did not confirm the new token.")


def rotate_token(env_file: Path, apply: bool) -> int:
    if not env_file.is_file():
        raise ValueError(f"Cannot rotate the token because {env_file} does not exist.")
    original_env_bytes = env_file.read_bytes()
    try:
        original_env = original_env_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{env_file} must be UTF-8 text.") from error

    settings = read_env_file(env_file)
    missing = [key for key in TOKEN_REQUIRED_KEYS if not settings.get(key)]
    if missing:
        raise ValueError(
            "Missing setting(s): " + ", ".join(missing)
            + f". Set them in {env_file} or in the process environment."
        )
    remote_root = settings["REMOTE_ROOT"].rstrip("/") or "/"
    remote_dir = posixpath.normpath(posixpath.join(remote_root, "..", "ws"))
    if not apply:
        print("Dry-run : générerait un nouveau jeton, mettrait à jour .env.local et /www/ws/config.local.php.")
        print(f"Destination OVH : {posixpath.join(remote_dir, 'config.local.php')}")
        print("Aucun jeton n’a été généré et aucun fichier n’a été modifié.")
        return 0

    token = secrets.token_urlsafe(32)
    updated_env = update_env_token_text(original_env, token)
    ftp: ftplib.FTP | None = None
    old_remote_config: bytes | None = None
    remote_updated = False
    try:
        ftp = open_ftp(settings)
        ftp.cwd(remote_dir)
        htaccess = ftp_read_file(ftp, ".htaccess").decode("utf-8", "replace")
        if r"config\.local" not in htaccess or not re.search(r"Require\s+all\s+denied", htaccess, re.I):
            raise RuntimeError("Remote .htaccess does not confirm that config.local.php is blocked from web access.")

        old_remote_config = ftp_read_file(ftp, "config.local.php")
        try:
            old_config_text = old_remote_config.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Remote config.local.php is not UTF-8 text.") from error
        new_remote_config = update_remote_config_text(old_config_text, token).encode("utf-8")

        remote_updated = True
        ftp.storbinary("STOR config.local.php", io.BytesIO(new_remote_config))
        if ftp_read_file(ftp, "config.local.php") != new_remote_config:
            raise RuntimeError("Remote config.local.php did not match the uploaded version.")

        verify_new_token(settings["SITE_URL"], token)
        replace_env_file(env_file, updated_env)
    except Exception as error:
        if remote_updated and ftp is not None and old_remote_config is not None:
            try:
                ftp.storbinary("STOR config.local.php", io.BytesIO(old_remote_config))
                if ftp_read_file(ftp, "config.local.php") != old_remote_config:
                    raise RuntimeError("Remote rollback verification failed.")
            except Exception as rollback_error:
                raise RuntimeError(
                    "Token rotation failed and the previous OVH config could not be restored; "
                    "check /www/ws/config.local.php before making further requests."
                ) from rollback_error
        raise error
    finally:
        if ftp is not None:
            try:
                ftp.quit()
            except ftplib.all_errors:
                ftp.close()

    print("Nouveau jeton déployé sur OVH et enregistré dans .env.local (valeur masquée).")
    print("Vérification HTTPS réussie : le WS accepte le nouveau jeton.")
    if os.environ.get(TOKEN_CONSTANT):
        print(
            "Attention : GRIMPEROOTS_WS_TOKEN est exporté dans l’environnement courant ; "
            "exécuter 'unset GRIMPEROOTS_WS_TOKEN' pour utiliser la valeur de .env.local."
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deploy a versioned custom Joomla WS PHP endpoint to /www/ws/ via FTP."
    )
    parser.add_argument(
        "filename", nargs="?", default="article-photos.php",
        help="Endpoint filename from joomla_custom/www/ws/ (default: article-photos.php).",
    )
    parser.add_argument(
        "--env-file", type=Path, default=DEFAULT_ENV_FILE,
        help=f"FTP settings file (default: {DEFAULT_ENV_FILE}).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Show the target without uploading (default).")
    mode.add_argument("--apply", action="store_true", help="Upload the endpoint and verify its remote checksum.")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing an existing remote file.")
    parser.add_argument(
        "--token", action="store_true",
        help="Generate and deploy a new WS token to OVH and .env.local (requires --apply).",
    )
    args = parser.parse_args()

    try:
        if args.token:
            if args.filename != "article-photos.php" or args.overwrite:
                parser.error("--token cannot be combined with an endpoint filename or --overwrite.")
            if not args.apply and not args.dry_run:
                return rotate_token(args.env_file, apply=False)
            return rotate_token(args.env_file, apply=args.apply)
        return deploy(args.filename, args.env_file, args.apply, args.overwrite)
    except FileExistsError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Deployment failed ({type(error).__name__}); check FTP settings and access.", file=sys.stderr)
        return 1
    except ftplib.all_errors as error:
        print(f"Deployment failed ({type(error).__name__}); check FTP settings and access.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
