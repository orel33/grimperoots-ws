#!/usr/bin/env python3
"""Archive the current proposal cycle and initialize an empty one."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_DATA_DIR = Path("data")


def archive_path(archive_dir: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    candidate = archive_dir / f"proposals-{timestamp}.json"
    suffix = 1
    while candidate.exists():
        candidate = archive_dir / f"proposals-{timestamp}-{suffix:02d}.json"
        suffix += 1
    return candidate


def write_empty_proposals(path: Path) -> None:
    temporary = path.with_name(f"{path.name}.tmp")
    try:
        temporary.write_text("{}\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def initialize_cycle(data_dir: Path) -> tuple[Path | None, bool]:
    proposals_path = data_dir / "proposals.json"
    archive_dir = data_dir / "archive"

    if proposals_path.exists():
        try:
            content = proposals_path.read_bytes()
            payload = json.loads(content)
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Impossible de lire {proposals_path} comme JSON valide : {error}") from error
        if not isinstance(payload, dict):
            raise RuntimeError(f"{proposals_path} doit être un objet JSON indexé par ID d'article.")
        if payload:
            archive_dir.mkdir(parents=True, exist_ok=True)
            destination = archive_path(archive_dir)
            try:
                with destination.open("xb") as archive_file:
                    archive_file.write(content)
                    archive_file.flush()
                    os.fsync(archive_file.fileno())
            except OSError:
                destination.unlink(missing_ok=True)
                raise
            write_empty_proposals(proposals_path)
            return destination, True

        return None, False

    data_dir.mkdir(parents=True, exist_ok=True)
    write_empty_proposals(proposals_path)
    return None, True


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Archive le cycle courant de data/proposals.json, puis démarre un cycle vide. "
            "Cette commande ne contacte pas Joomla et ne modifie pas les exports."
        ),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Répertoire des propositions (défaut : {DEFAULT_DATA_DIR}).",
    )
    args = parser.parse_args()

    proposals_path = args.data_dir / "proposals.json"
    print("Fichier lu implicitement :")
    print(f"  - {proposals_path}")
    print("Aucun export Joomla ni fichier de configuration n'est lu.")

    try:
        archived, initialized = initialize_cycle(args.data_dir)
    except (OSError, RuntimeError) as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1

    if not initialized:
        print(f"{proposals_path} est déjà vide ; aucune archive créée.")
        return 0
    if archived is not None:
        print(f"Ancien cycle archivé : {archived}")
    print(f"Nouveau cycle initialisé dans {proposals_path} avec un objet JSON vide.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
