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
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from fetch_articles import load_settings


PROJECT_DIR = Path(__file__).resolve().parent
CSS_SOURCE = PROJECT_DIR / "assets" / "article.css"


def site_root_url(base_url: str) -> str:
    """Remove an optional Joomla API suffix to get the site's public root."""
    root = base_url.rstrip("/")
    for suffix in ("/api/index.php/v1", "/api/index.php", "/api"):
        if root.endswith(suffix):
            return root[: -len(suffix)]
    return root


def report_implicit_inputs(input_dir: Path) -> None:
    print("Fichiers d'entrée implicites :", file=sys.stderr)
    env_files = [path for path in (Path(".env"), Path(".env.local")) if path.is_file()]
    if env_files:
        for path in env_files:
            print(f"  - {path} (configuration Joomla)", file=sys.stderr)
    else:
        print("  - aucun fichier .env présent (configuration via l'environnement)", file=sys.stderr)

    required = input_dir / "articles.json"
    print(f"  - {required} (article sélectionné par ID)", file=sys.stderr)
    for filename in ("authors.json", "categories.json", "tags.json"):
        path = input_dir / filename
        status = "lu si présent" if path.is_file() else "optionnel, absent"
        print(f"  - {path} ({status})", file=sys.stderr)
    print(f"  - {CSS_SOURCE} (feuille de style copiée vers le rendu)", file=sys.stderr)
    print("  Les images restent distantes ; aucun fichier image local n'est lu.", file=sys.stderr)


class RemoteImageLinks(HTMLParser):
    """Make relative image URLs absolute while preserving the article markup."""

    def __init__(self, site_root: str, base_url: str, replace_galleries: bool) -> None:
        super().__init__(convert_charrefs=False)
        self.site_root = site_root.rstrip("/") + "/" if site_root else ""
        self.base_url = base_url.rstrip("/")
        self.base_origin = urlsplit(self.base_url)[:2]
        self.replace_galleries = replace_galleries
        self.parts: list[str] = []
        self.gallery_depth = 0
        self.gallery_buffer: list[str] = []
        self.gallery_image_urls: list[str] = []

    def append(self, value: str) -> None:
        if self.gallery_depth:
            self.gallery_buffer.append(value)
        else:
            self.parts.append(value)

    def gallery_url(self) -> str | None:
        """Find the common images/albums directory represented by this SIG gallery."""
        image_directories: list[tuple[str, ...]] = []
        base_origin = self.base_origin
        if not base_origin[0] or not base_origin[1]:
            return None

        for image_url in self.gallery_image_urls:
            resolved = urljoin(self.base_url + "/", image_url)
            parsed = urlsplit(resolved)
            if parsed[:2] != base_origin:
                return None
            path = unquote(parsed.path)
            marker = "/images/albums/"
            marker_index = path.find(marker)
            if marker_index < 0:
                return None
            relative_image = path[marker_index + len(marker) :]
            directory = PurePosixPath(relative_image).parent
            if not relative_image or str(directory) == ".":
                return None
            image_directories.append(directory.parts)

        if not image_directories:
            return None
        common_parts: list[str] = []
        for segments in zip(*image_directories):
            if len(set(segments)) != 1:
                break
            common_parts.append(segments[0])
        if not common_parts:
            return None

        public_root = urlsplit(self.site_root)
        if public_root[:2] != base_origin:
            return None
        root_path = public_root.path.rstrip("/")
        gallery_path = (
            f"{root_path}/images/albums/{quote('/'.join(common_parts), safe='/')}/"
        )
        return urlunsplit((base_origin[0], base_origin[1], gallery_path, "", ""))

    def finish_gallery(self) -> None:
        destination = self.gallery_url()
        if destination:
            self.parts.append(
                f'<a class="article-gallery-link" href="{escape(destination, quote=True)}">gallery</a>'
            )
        else:
            self.parts.extend(self.gallery_buffer)
        self.gallery_buffer = []
        self.gallery_image_urls = []

    def remote_url(self, value: str) -> str:
        value = value.strip()
        if not value or value.startswith(("#", "data:", "javascript:")):
            return value
        return urljoin(self.site_root, value) if self.site_root else value

    def render_start_tag(self, tag: str, attrs: list[tuple[str, str | None]], closed: bool) -> None:
        tag_name = tag.lower()
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        is_gallery = tag_name == "div" and "sigplus-gallery" in classes
        if self.replace_galleries and not self.gallery_depth and is_gallery:
            self.gallery_depth = 1
            self.gallery_buffer = []
            self.gallery_image_urls = []
        elif self.gallery_depth and tag_name == "div":
            self.gallery_depth += 1

        if (
            self.gallery_depth
            and tag_name == "a"
            and "sigplus-image" in classes
            and attributes.get("href")
        ):
            self.gallery_image_urls.append(attributes["href"])

        rewritten: list[str] = []
        for name, value in attrs:
            if value is not None and tag_name in ("img", "source"):
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
        self.append(f"<{tag}{(' ' + ' '.join(rewritten)) if rewritten else ''}{suffix}")

        if closed and self.gallery_depth and tag_name == "div":
            self.gallery_depth -= 1
            if self.gallery_depth == 0:
                self.finish_gallery()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.render_start_tag(tag, attrs, closed=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.render_start_tag(tag, attrs, closed=True)

    def handle_endtag(self, tag: str) -> None:
        self.append(f"</{tag}>")
        if self.gallery_depth and tag.lower() == "div":
            self.gallery_depth -= 1
            if self.gallery_depth == 0:
                self.finish_gallery()

    def handle_data(self, data: str) -> None:
        self.append(data)

    def handle_entityref(self, name: str) -> None:
        self.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self.append(f"<!{decl}>")

    def unknown_decl(self, data: str) -> None:
        self.append(f"<![{data}]>")


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
    resource: dict,
    attributes: dict,
    base_url: str,
    authors: dict[str, str],
    categories: dict[str, str],
    tags_by_id: dict[str, str],
    replace_galleries: bool,
) -> str:
    content = attributes.get("text", "")
    if isinstance(content, dict):
        content = "\n".join(
            part for part in (content.get("introtext"), content.get("fulltext")) if isinstance(part, str)
        )
    if not isinstance(content, str):
        content = ""

    parser = RemoteImageLinks(site_root_url(base_url), base_url, replace_galleries)
    parser.feed(content)
    parser.close()
    body = "".join(parser.parts)

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


def article_resource(payload: object, article_id: int, path: Path) -> tuple[dict, dict]:
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    resources = payload.get("data")
    if not isinstance(resources, list):
        raise ValueError(f"{path} does not contain an article list.")
    resource = next(
        (item for item in resources if isinstance(item, dict) and str(item.get("id")) == str(article_id)),
        None,
    )
    if not isinstance(resource, dict):
        raise ValueError(f"Article {article_id} was not found in {path}.")
    attributes = resource.get("attributes", resource)
    if not isinstance(attributes, dict):
        raise ValueError(f"Article {article_id} in {path} contains invalid attributes.")
    return resource, attributes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render saved Joomla article JSON exports as HTML."
    )
    parser.add_argument(
        "article_id",
        type=int,
        help="Joomla article ID to render from data/articles.json.",
    )
    parser.add_argument("--input-dir", type=Path, default=Path("data"), help="Directory containing articles.json and lookup exports.")
    parser.add_argument("--output-dir", type=Path, default=Path("output"), help="Directory for generated HTML files.")
    parser.add_argument(
        "--gallery",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Replace rendered SIG galleries with a link to their image directory (default: enabled).",
    )
    args = parser.parse_args()
    report_implicit_inputs(args.input_dir)
    if args.article_id < 1:
        parser.error("article_id must be a positive integer")

    articles_path = args.input_dir / "articles.json"
    if not articles_path.is_file():
        print(f"Article export not found: {articles_path}", file=sys.stderr)
        return 1

    try:
        settings = load_settings()
    except (OSError, ValueError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    base_url = settings.get("JOOMLA_BASE_URL", "").strip()

    try:
        payload = json.loads(articles_path.read_text(encoding="utf-8"))
        resource, attributes = article_resource(payload, args.article_id, articles_path)
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
        html = article_html(resource, attributes, base_url, authors, categories, tags_by_id, args.gallery)
        destination = args.output_dir / f"{args.article_id}.html"
        destination.write_text(html, encoding="utf-8")
    except OSError as error:
        print(f"Could not write HTML output: {error}", file=sys.stderr)
        return 1

    print(f"Rendered article {args.article_id} into {destination}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
