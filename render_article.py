#!/usr/bin/env python3
"""Render saved Joomla article JSON exports as standalone HTML pages."""

from __future__ import annotations

import argparse
from html import escape
from html.parser import HTMLParser
import json
import shutil
import sys
from pathlib import Path
from urllib.parse import urljoin

from fetch_article import load_settings


PROJECT_DIR = Path(__file__).resolve().parent
CSS_SOURCE = PROJECT_DIR / "assets" / "article.css"


def site_root_url(base_url: str) -> str:
    """Remove an optional Joomla API suffix to get the site's public root."""
    root = base_url.rstrip("/")
    for suffix in ("/api/index.php/v1", "/api/index.php", "/api"):
        if root.endswith(suffix):
            return root[: -len(suffix)]
    return root


class RemoteImageLinks(HTMLParser):
    """Make relative image URLs absolute while preserving the article markup."""

    def __init__(self, site_root: str) -> None:
        super().__init__(convert_charrefs=False)
        self.site_root = site_root.rstrip("/") + "/" if site_root else ""
        self.parts: list[str] = []

    def remote_url(self, value: str) -> str:
        value = value.strip()
        if not value or value.startswith(("#", "data:", "javascript:")):
            return value
        return urljoin(self.site_root, value) if self.site_root else value

    def render_start_tag(self, tag: str, attrs: list[tuple[str, str | None]], closed: bool) -> None:
        rewritten: list[str] = []
        for name, value in attrs:
            if value is not None and tag.lower() in ("img", "source"):
                if name.lower() == "src":
                    value = self.remote_url(value)
                elif name.lower() == "srcset" and not value.lstrip().lower().startswith("data:"):
                    candidates = []
                    for candidate in value.split(","):
                        fields = candidate.strip().split()
                        if fields:
                            fields[0] = self.remote_url(fields[0])
                            candidates.append(" ".join(fields))
                    value = ", ".join(candidates)
            if value is None:
                rewritten.append(name)
            else:
                rewritten.append(f'{name}="{escape(value, quote=True)}"')
        suffix = " />" if closed else ">"
        self.parts.append(f"<{tag}{(' ' + ' '.join(rewritten)) if rewritten else ''}{suffix}")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.render_start_tag(tag, attrs, closed=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.render_start_tag(tag, attrs, closed=True)

    def handle_endtag(self, tag: str) -> None:
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self.parts.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self.parts.append(f"<!{decl}>")

    def unknown_decl(self, data: str) -> None:
        self.parts.append(f"<![{data}]>")


def load_name_lookup(directory: Path, filename: str, name_keys: tuple[str, ...]) -> dict[str, str]:
    """Load an optional local Joomla ID-to-name export."""
    path = directory / filename
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    records = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        return {}

    lookup: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        attributes = record.get("attributes", {})
        if not isinstance(attributes, dict):
            attributes = {}
        item_id = record.get("id", attributes.get("id"))
        name = next(
            (
                value
                for key in name_keys
                for value in (attributes.get(key), record.get(key))
                if isinstance(value, str) and value.strip()
            ),
            None,
        )
        if item_id is not None and name is not None:
            lookup[str(item_id)] = name.strip()
    return lookup


def relationship_id(resource: dict, relationship_name: str) -> str | None:
    relationships = resource.get("relationships", {})
    relationship = relationships.get(relationship_name, {}) if isinstance(relationships, dict) else {}
    related = relationship.get("data") if isinstance(relationship, dict) else None
    if isinstance(related, dict) and related.get("id") is not None:
        return str(related["id"])
    return None


def display_reference(item_id: str | int, names: dict[str, str]) -> str:
    item_id = str(item_id)
    name = names.get(item_id)
    return f"{name} ({item_id})" if name else item_id


def article_html(
    payload: dict,
    attributes: dict,
    site_root: str,
    authors: dict[str, str],
    categories: dict[str, str],
    tags_by_id: dict[str, str],
) -> str:
    content = attributes.get("text", "")
    if isinstance(content, dict):
        content = "\n".join(
            part for part in (content.get("introtext"), content.get("fulltext")) if isinstance(part, str)
        )
    if not isinstance(content, str):
        content = ""

    parser = RemoteImageLinks(site_root)
    parser.feed(content)
    parser.close()
    body = "".join(parser.parts)

    resource = payload.get("data", payload)
    if isinstance(resource, list):
        resource = resource[0] if resource else {}
    if not isinstance(resource, dict):
        resource = {}
    article_id = attributes.get("id", resource.get("id", ""))
    metadata: list[tuple[str, str]] = [("ID", str(article_id))]
    for label, keys in (("Alias", ("alias",)), ("Création", ("created",)), ("Modification", ("modified",))):
        value = next((attributes.get(key) for key in keys if attributes.get(key) not in (None, "")), None)
        if value is not None:
            metadata.append((label, str(value)))

    author_id = relationship_id(resource, "created_by")
    if author_id is None and attributes.get("created_by") not in (None, ""):
        author_id = str(attributes["created_by"])
    if author_id is not None:
        metadata.append(("Auteur", display_reference(author_id, authors)))

    category_id = relationship_id(resource, "category")
    if category_id is None:
        raw_category = next(
            (attributes.get(key) for key in ("catid", "category_id") if attributes.get(key) not in (None, "")),
            None,
        )
        if raw_category is not None:
            category_id = str(raw_category)
    if category_id is not None:
        metadata.append(("Catégorie", display_reference(category_id, categories)))
    else:
        category_name = next(
            (attributes.get(key) for key in ("category_title", "category") if attributes.get(key) not in (None, "")),
            None,
        )
        if category_name is not None:
            metadata.append(("Catégorie", str(category_name)))

    tag_ids: list[str] = []
    relationships = resource.get("relationships", {})
    tag_relationship = relationships.get("tags", {}) if isinstance(relationships, dict) else {}
    related_tags = tag_relationship.get("data", []) if isinstance(tag_relationship, dict) else []
    if isinstance(related_tags, list):
        tag_ids = [str(tag["id"]) for tag in related_tags if isinstance(tag, dict) and tag.get("id") is not None]
    raw_tags = attributes.get("tags")
    if not tag_ids and isinstance(raw_tags, dict):
        tag_ids = [str(tag_id) for tag_id in raw_tags]
    elif not tag_ids and isinstance(raw_tags, list):
        tag_ids = [
            str(tag.get("id")) if isinstance(tag, dict) else str(tag)
            for tag in raw_tags
            if (isinstance(tag, dict) and tag.get("id") is not None) or isinstance(tag, (str, int))
        ]
    if tag_ids:
        tag_values = (display_reference(tag_id, tags_by_id) for tag_id in tag_ids)
        metadata.append(("Tags existants", ", ".join(tag_values)))

    title = str(attributes.get("title") or f"Article {article_id}")
    metadata_html = "\n".join(
        f"      <dt>{escape(label)}</dt><dd>{escape(value)}</dd>" for label, value in metadata
    )
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <link rel="stylesheet" href="article.css">
</head>
<body>
  <header>
    <h1>{escape(title)}</h1>
    <dl>
{metadata_html}
    </dl>
  </header>
  <main>
    <article>
{body}
    </article>
  </main>
</body>
</html>
"""


def article_resource(payload: object, path: Path) -> tuple[dict, dict]:
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    resource = payload.get("data", payload)
    if isinstance(resource, list):
        resource = resource[0] if resource else {}
    if not isinstance(resource, dict):
        raise ValueError(f"{path} does not contain an article resource.")
    attributes = resource.get("attributes", resource)
    if not isinstance(attributes, dict):
        raise ValueError(f"{path} contains invalid article attributes.")
    return payload, attributes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render saved Joomla article JSON exports as HTML."
    )
    parser.add_argument(
        "article_id",
        type=int,
        nargs="?",
        help="Render only this article ID; without it, render all numeric JSON files in data/.",
    )
    parser.add_argument("--input-dir", type=Path, default=Path("data"), help="Directory containing raw JSON exports.")
    parser.add_argument("--output-dir", type=Path, default=Path("output"), help="Directory for generated HTML files.")
    args = parser.parse_args()
    if args.article_id is not None and args.article_id < 1:
        parser.error("article_id must be a positive integer")

    if args.article_id is not None:
        sources = [args.input_dir / f"{args.article_id}.json"]
        if not sources[0].is_file():
            print(f"Article JSON not found: {sources[0]}", file=sys.stderr)
            return 1
    else:
        sources = sorted(
            path for path in args.input_dir.glob("*.json") if path.stem.isdecimal()
        )
        if not sources:
            print(f"No article JSON files found in {args.input_dir}.", file=sys.stderr)
            return 1

    try:
        settings = load_settings()
    except (OSError, ValueError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    site_root = site_root_url(settings.get("JOOMLA_BASE_URL", "").strip())

    try:
        articles = []
        for source in sources:
            payload = json.loads(source.read_text(encoding="utf-8"))
            articles.append((source, *article_resource(payload, source)))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Could not read article JSON: {error}", file=sys.stderr)
        return 1

    authors = load_name_lookup(args.input_dir, "authors.json", ("name",))
    categories = load_name_lookup(args.input_dir, "categories.json", ("title", "name"))
    tags_by_id = load_name_lookup(args.input_dir, "tags.json", ("title", "name"))

    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        if not CSS_SOURCE.is_file():
            raise FileNotFoundError(f"Stylesheet not found: {CSS_SOURCE}")
        css_path = args.output_dir / "article.css"
        if CSS_SOURCE.resolve() != css_path.resolve():
            shutil.copyfile(CSS_SOURCE, css_path)
        for source, payload, attributes in articles:
            html = article_html(payload, attributes, site_root, authors, categories, tags_by_id)
            destination = args.output_dir / f"{source.stem}.html"
            destination.write_text(html, encoding="utf-8")
    except OSError as error:
        print(f"Could not write HTML output: {error}", file=sys.stderr)
        return 1

    print(f"Rendered {len(articles)} article(s) into {args.output_dir}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
