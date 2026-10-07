#!/usr/bin/env python3
"""Apply human-validated article tag proposals to Joomla via Web Services API."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import ssl
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = PROJECT_DIR / "data"
DEFAULT_LOGS_DIR = PROJECT_DIR / "logs"
ENV_KEYS = ("JOOMLA_BASE_URL", "JOOMLA_TOKEN")


class ApplyError(RuntimeError):
    """A safe, user-facing error during proposal validation or API access."""


class RefuseRedirectHandler(HTTPRedirectHandler):
    """Never forward the Joomla token to a redirected URL."""

    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, raw_value = line.partition("=")
        key = key.strip()
        if not separator or key not in ENV_KEYS:
            continue
        try:
            parsed = shlex.split(raw_value, comments=True, posix=True)
        except ValueError as error:
            raise ApplyError(f"Valeur invalide pour {key} dans {path}.") from error
        values[key] = parsed[0] if parsed else ""
    return values


def load_settings() -> dict[str, str]:
    settings: dict[str, str] = {}
    for filename in (".env", ".env.local"):
        settings.update(read_env_file(PROJECT_DIR / filename))
    settings.update({key: os.environ[key] for key in ENV_KEYS if os.environ.get(key)})
    return settings


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


def article_endpoint(base_url: str, article_id: int) -> str:
    base_url = base_url.rstrip("/")
    path = urlsplit(base_url).path.rstrip("/")
    if path.endswith("/api/index.php/v1"):
        return f"{base_url}/content/articles/{article_id}"
    if path.endswith("/api/index.php"):
        return f"{base_url}/v1/content/articles/{article_id}"
    return f"{base_url}/api/index.php/v1/content/articles/{article_id}"


def api_request(
    url: str,
    token: str,
    ssl_context: ssl.SSLContext,
    method: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {
        "Accept": "application/vnd.api+json",
        "X-Joomla-Token": token,
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        opener = build_opener(HTTPSHandler(context=ssl_context), RefuseRedirectHandler)
        with opener.open(request, timeout=30) as response:
            response_body = response.read()
    except HTTPError as error:
        message = f"Joomla a répondu HTTP {error.code} ({error.reason}) pour {method}."
        try:
            error_body = error.read(4096).decode("utf-8", errors="replace")
        except OSError:
            error_body = ""
        error_detail = " ".join(error_body.split())
        if token:
            error_detail = error_detail.replace(token, "[jeton masqué]")
        if error_detail:
            if len(error_detail) > 1200:
                error_detail = error_detail[:1200] + "… [réponse tronquée]"
            message += f" Détail Joomla : {error_detail}"
        if error.code == 401:
            message += " Vérifie le token et les permissions API."
        raise ApplyError(message) from error
    except URLError as error:
        reason = error.reason
        if isinstance(reason, ssl.SSLCertVerificationError):
            raise ApplyError(
                "Échec de vérification du certificat TLS ; la vérification reste activée."
            ) from error
        raise ApplyError(f"Impossible de joindre Joomla : {reason}") from error
    except TimeoutError as error:
        raise ApplyError("La requête Joomla a expiré.") from error

    if not response_body:
        return None
    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError as error:
        raise ApplyError("Joomla a renvoyé une réponse qui n'est pas du JSON valide.") from error
    if not isinstance(parsed, dict):
        raise ApplyError("Joomla a renvoyé une structure JSON inattendue.")
    return parsed


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ApplyError(f"Fichier requis absent : {path}") from error
    except json.JSONDecodeError as error:
        raise ApplyError(f"JSON invalide dans {path} : {error}") from error


def parse_id(value: Any, context: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ApplyError(f"Identifiant invalide dans {context} : {value!r}.") from error
    if parsed <= 0:
        raise ApplyError(f"Identifiant invalide dans {context} : {value!r}.")
    return parsed


def ids_from_values(values: Any, context: str) -> list[int]:
    if not isinstance(values, list):
        raise ApplyError(f"{context} doit être une liste d'identifiants.")
    return list(dict.fromkeys(parse_id(value, context) for value in values))


def resource_from_response(payload: dict[str, Any], context: str) -> dict[str, Any]:
    resource = payload.get("data", payload)
    if not isinstance(resource, dict):
        raise ApplyError(f"Joomla n'a pas renvoyé {context} comme une ressource JSON.")
    return resource


def resource_attributes(resource: dict[str, Any]) -> dict[str, Any]:
    attributes = resource.get("attributes", resource)
    return attributes if isinstance(attributes, dict) else {}


def ids_from_relation_data(data: Any) -> list[int] | None:
    if data is None:
        return []
    if isinstance(data, list):
        output: list[int] = []
        for item in data:
            value = item.get("id") if isinstance(item, dict) else item
            output.append(parse_id(value, "relation tags"))
        return list(dict.fromkeys(output))
    if isinstance(data, dict):
        if data.get("id") is not None:
            return [parse_id(data["id"], "relation tags")]
        return [parse_id(key, "relation tags") for key in data]
    return None


def article_tag_ids(resource: dict[str, Any]) -> list[int]:
    relationships = resource.get("relationships")
    if isinstance(relationships, dict):
        tags_relation = relationships.get("tags")
        if isinstance(tags_relation, dict) and "data" in tags_relation:
            ids = ids_from_relation_data(tags_relation["data"])
            if ids is not None:
                return ids

    attributes = resource_attributes(resource)
    if "tags" in attributes:
        raw_tags = attributes["tags"]
        if isinstance(raw_tags, dict):
            return list(dict.fromkeys(parse_id(key, "article tags") for key in raw_tags))
        if isinstance(raw_tags, list):
            values = [item.get("id") if isinstance(item, dict) else item for item in raw_tags]
            return list(dict.fromkeys(parse_id(value, "article tags") for value in values))
    raise ApplyError("La réponse Joomla ne contient pas les tags actuels de l'article.")


def load_tag_names(path: Path) -> dict[int, str]:
    payload = read_json(path)
    resources = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(resources, list):
        raise ApplyError(f"{path} doit contenir une collection JSON:API dans data.")
    result: dict[int, str] = {}
    for resource in resources:
        if not isinstance(resource, dict):
            raise ApplyError(f"Tag invalide dans {path}.")
        attributes = resource_attributes(resource)
        tag_id = parse_id(resource.get("id", attributes.get("id")), str(path))
        title = attributes.get("title") or attributes.get("name")
        if not isinstance(title, str) or not title.strip():
            raise ApplyError(f"Le tag {tag_id} n'a pas de titre dans {path}.")
        result[tag_id] = title.strip()
    return result


def load_proposal(data_dir: Path, article_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = read_json(data_dir / "proposals.json")
    if not isinstance(payload, dict):
        raise ApplyError("data/proposals.json doit être un objet indexé par ID d'article.")
    entry = payload.get(str(article_id))
    if not isinstance(entry, dict):
        raise ApplyError(f"Aucune proposition locale pour l'article {article_id}.")
    review = entry.get("review")
    if not isinstance(review, dict) or review.get("status") != "validated":
        raise ApplyError(
            f"La proposition de l'article {article_id} n'a pas le statut review.status=validated."
        )
    return entry, review


def load_proposal_ids(data_dir: Path) -> tuple[list[int], list[tuple[int, str]]]:
    payload = read_json(data_dir / "proposals.json")
    if not isinstance(payload, dict):
        raise ApplyError("data/proposals.json doit être un objet indexé par ID d'article.")
    validated: list[int] = []
    skipped: list[tuple[int, str]] = []
    for raw_id, entry in payload.items():
        article_id = parse_id(raw_id, "clé de proposals.json")
        review = entry.get("review") if isinstance(entry, dict) else None
        if isinstance(review, dict) and review.get("status") == "validated":
            validated.append(article_id)
        else:
            title = entry.get("title", "") if isinstance(entry, dict) else ""
            skipped.append((article_id, str(title)))
    return sorted(validated), sorted(skipped)


def ids_from_proposal(
    entry: dict[str, Any], review: dict[str, Any]
) -> tuple[list[int], list[int], list[int]]:
    baseline = ids_from_values(entry.get("existing_tags"), "existing_tags")
    final_ids = ids_from_values(review.get("final_tags"), "review.final_tags")
    approved_removals: list[int] = []
    for field in ("removed_tags", "validated_removed_tags"):
        if field in review:
            approved_removals.extend(ids_from_values(review[field], f"review.{field}"))
    approved_removals = list(dict.fromkeys(approved_removals))
    if set(approved_removals) - set(baseline):
        raise ApplyError("review.removed_tags contient un tag absent des tags existants exportés.")
    return baseline, final_ids, approved_removals


def names_for(ids: list[int], tag_names: dict[int, str]) -> list[str]:
    return [f"{tag_names.get(tag_id, 'Tag inconnu')} ({tag_id})" for tag_id in ids]


def unique_log_path(logs_dir: Path, article_id: int) -> Path:
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d-%H%M%S")
    base = logs_dir / f"apply-{stamp}-article-{article_id}.json"
    path = base
    suffix = 2
    while path.exists():
        path = base.with_name(f"{base.stem}-{suffix}{base.suffix}")
        suffix += 1
    return path


def write_log(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def process_article(
    article_id: int,
    data_dir: Path,
    logs_dir: Path,
    tag_names: dict[int, str],
    base_url: str,
    token: str,
    ssl_context: ssl.SSLContext,
    apply_changes: bool,
    label: str = "",
) -> bool:
    try:
        proposal, review = load_proposal(data_dir, article_id)
        baseline, final_ids, approved_removals = ids_from_proposal(proposal, review)
        unknown = sorted(set(final_ids) - set(tag_names))
        if unknown:
            raise ApplyError("Tag(s) absent de l'export Joomla local : " + ", ".join(map(str, unknown)))

        endpoint = article_endpoint(base_url, article_id)
        response = api_request(endpoint, token, ssl_context, "GET")
        if response is None:
            raise ApplyError("Joomla a renvoyé une réponse vide pour l'article.")
        article = resource_from_response(response, "l'article")
        returned_id = parse_id(article.get("id", resource_attributes(article).get("id")), "article Joomla")
        if returned_id != article_id:
            raise ApplyError(f"L'API a renvoyé l'article {returned_id} au lieu de {article_id}.")
        current_ids = article_tag_ids(article)
        title = resource_attributes(article).get("title") or proposal.get("title") or f"Article {article_id}"

        print(f"{label}Article {article_id} — {title}")
        if set(current_ids) == set(final_ids):
            print("  Tags déjà conformes ; aucun changement.")
            return True

        if set(current_ids) != set(baseline):
            current_display = ", ".join(names_for(current_ids, tag_names)) or "aucun"
            baseline_display = ", ".join(names_for(baseline, tag_names)) or "aucun"
            raise ApplyError(
                "Les tags Joomla actuels diffèrent de existing_tags dans la proposition. "
                f"Actuels : [{current_display}]. Exportés : [{baseline_display}]. "
                "Actualise les exports et fais relire la proposition avant de continuer."
            )

        actual_removals = sorted(set(current_ids) - set(final_ids))
        if set(actual_removals) - set(approved_removals):
            raise ApplyError("Refus d'écriture : un tag existant serait retiré sans validation humaine explicite.")

        expected_additions = sorted(set(final_ids) - set(current_ids))
        declared_additions = ids_from_values(proposal.get("new_tags", []), "new_tags")
        if set(expected_additions) != set(declared_additions):
            raise ApplyError("new_tags ne correspond pas aux ajouts calculés depuis les tags actuels.")

        diff = [f"+{names_for([tag_id], tag_names)[0]}" for tag_id in expected_additions]
        diff.extend(f"-{names_for([tag_id], tag_names)[0]}" for tag_id in actual_removals)
        print("  " + ("  ".join(diff) if diff else "Aucun changement"))

        if not apply_changes:
            print("  Simulation : aucun PATCH envoyé.")
            return True

        log_path = unique_log_path(logs_dir, article_id)
        log_entry: dict[str, Any] = {
            "article_id": article_id,
            "title": title,
            "before": current_ids,
            "after": final_ids,
            "added": expected_additions,
            "removed": actual_removals,
            "status": "prepared",
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        write_log(log_path, log_entry)
        log_entry["status"] = "applying"
        write_log(log_path, log_entry)
        try:
            api_request(
                endpoint,
                token,
                ssl_context,
                "PATCH",
                {"id": article_id, "tags": final_ids},
            )
        except ApplyError as patch_error:
            log_entry["error"] = str(patch_error)
            log_entry["status"] = "patch_error_reconciling"
            write_log(log_path, log_entry)
            try:
                reconciliation = api_request(endpoint, token, ssl_context, "GET")
                if reconciliation is None:
                    raise ApplyError("Réponse vide pendant la relecture après erreur PATCH.")
                reconciled_article = resource_from_response(reconciliation, "l'article après erreur PATCH")
                observed_ids = article_tag_ids(reconciled_article)
            except ApplyError as read_error:
                log_entry["status"] = "patch_error_state_unknown"
                log_entry["reconciliation_error"] = str(read_error)
                log_entry["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                write_log(log_path, log_entry)
                raise ApplyError(
                    f"{patch_error} La relecture après erreur a échoué ; état Joomla inconnu. Journal : {log_path}"
                ) from patch_error

            log_entry["observed_after"] = observed_ids
            log_entry["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            if set(observed_ids) == set(final_ids):
                log_entry["status"] = "patch_error_but_target_confirmed"
                write_log(log_path, log_entry)
                print(f"  PATCH en erreur, mais tags validés confirmés après relecture. Journal : {log_path}")
                return True
            if set(observed_ids) == set(current_ids):
                log_entry["status"] = "patch_error_no_change_confirmed"
                write_log(log_path, log_entry)
                raise ApplyError(
                    f"{patch_error} La relecture confirme que les tags sont inchangés. Journal : {log_path}"
                ) from patch_error

            log_entry["status"] = "patch_error_unexpected_state"
            write_log(log_path, log_entry)
            observed_display = ", ".join(names_for(observed_ids, tag_names)) or "aucun"
            raise ApplyError(
                f"{patch_error} La relecture a trouvé un état différent de l'avant et de la cible "
                f"([{observed_display}]). Journal : {log_path}"
            ) from patch_error

        log_entry["status"] = "patch_succeeded_verifying"
        write_log(log_path, log_entry)
        try:
            verification = api_request(endpoint, token, ssl_context, "GET")
            if verification is None:
                raise ApplyError("Réponse de vérification vide après PATCH.")
            verified_article = resource_from_response(verification, "l'article après PATCH")
            observed_ids = article_tag_ids(verified_article)
        except ApplyError as error:
            log_entry["status"] = "verification_failed"
            log_entry["error"] = str(error)
            log_entry["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            write_log(log_path, log_entry)
            raise

        log_entry["observed_after"] = observed_ids
        log_entry["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if set(observed_ids) != set(final_ids):
            log_entry["status"] = "verification_mismatch"
            write_log(log_path, log_entry)
            raise ApplyError(
                "Le PATCH a répondu, mais la relecture Joomla ne correspond pas aux tags validés. "
                f"Journal : {log_path}"
            )
        log_entry["status"] = "verified"
        write_log(log_path, log_entry)
        print(f"  Mise à jour confirmée par relecture Joomla. Journal : {log_path}")
        return True
    except (ApplyError, OSError) as error:
        print(f"{label}Article {article_id} — erreur : {error}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect or apply human-validated article tag proposals to Joomla."
    )
    parser.add_argument("article_id", type=int, nargs="?", help="Joomla article ID to inspect or update.")
    parser.add_argument("--all", action="store_true", help="Process every human-validated proposal.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Read Joomla and print the proposed change (default).")
    mode.add_argument("--apply", action="store_true", help="Write the validated tags to Joomla through PATCH.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--logs-dir", type=Path, default=DEFAULT_LOGS_DIR)
    args = parser.parse_args()

    if (args.article_id is None) == (not args.all):
        parser.error("indique un ID d'article ou --all, mais pas les deux.")
    if args.article_id is not None and args.article_id <= 0:
        parser.error("article_id must be a positive integer.")

    try:
        tag_names = load_tag_names(args.data_dir / "tags.json")
        settings = load_settings()
        base_url = settings.get("JOOMLA_BASE_URL", "").strip()
        token = settings.get("JOOMLA_TOKEN", "").strip()
        if not base_url or not token:
            raise ApplyError("Configure JOOMLA_BASE_URL et JOOMLA_TOKEN dans l'environnement, .env ou .env.local.")
        parsed_base = urlsplit(base_url)
        if parsed_base.scheme != "https" or not parsed_base.netloc:
            raise ApplyError("JOOMLA_BASE_URL doit être une URL https valide.")

        ssl_context = create_ssl_context()
        if args.all:
            article_ids, skipped = load_proposal_ids(args.data_dir)
            if skipped:
                print(f"{len(skipped)} proposition(s) ignorée(s), revue non validée :")
                for article_id, title in skipped:
                    print(f"  Article {article_id}" + (f" — {title}" if title else ""))
            if not article_ids:
                if skipped:
                    print("Aucune proposition validée à traiter.")
                    return 0
                raise ApplyError("Aucune proposition dans data/proposals.json.")
            print(f"{len(article_ids)} proposition(s) validée(s) à traiter")
            failures = 0
            for index, article_id in enumerate(article_ids, start=1):
                label = f"[{index}/{len(article_ids)}] "
                if not process_article(
                    article_id,
                    args.data_dir,
                    args.logs_dir,
                    tag_names,
                    base_url,
                    token,
                    ssl_context,
                    args.apply,
                    label,
                ):
                    failures += 1
            print(f"Terminé : {len(article_ids) - failures} réussi(s), {failures} erreur(s).")
            return 1 if failures else 0

        return 0 if process_article(
            args.article_id,
            args.data_dir,
            args.logs_dir,
            tag_names,
            base_url,
            token,
            ssl_context,
            args.apply,
        ) else 1
    except (ApplyError, OSError) as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
