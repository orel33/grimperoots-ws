#!/usr/bin/env python3
"""Deploy one versioned custom Joomla WS endpoint to the OVH hosting."""

from __future__ import annotations

import argparse
import ftplib
import hashlib
import io
import os
import posixpath
import shlex
import ssl
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WS_SOURCE_DIR = ROOT / "www" / "ws"
DEFAULT_ENV_FILE = Path(".env.local")
ENV_KEYS = ("FTP_HOST", "FTP_USER", "FTP_PASSWORD", "FTP_PLAIN", "REMOTE_ROOT")
REQUIRED_KEYS = ("FTP_HOST", "FTP_USER", "FTP_PASSWORD", "REMOTE_ROOT")
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
    if Path(filename).name != filename or not filename.endswith(".php") or filename.startswith("_"):
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
    args = parser.parse_args()

    try:
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
