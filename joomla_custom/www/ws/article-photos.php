<?php
declare(strict_types=1);

require_once __DIR__ . '/_common.php';

ws_require_get();
ws_require_token();

$articleId = filter_input(INPUT_GET, 'id', FILTER_VALIDATE_INT);
if ($articleId === false || $articleId === null || $articleId <= 0) {
    ws_json_response(['error' => 'Invalid id'], 400);
}

function inventory_inside_root(string $path, string $root): bool
{
    return str_starts_with($path, $root . DIRECTORY_SEPARATOR);
}

function inventory_relative_path(string $path): ?string
{
    $path = rawurldecode(str_replace('\\', '/', trim($path)));
    if ($path === '' || str_contains($path, "\0") || str_starts_with($path, '/')) {
        return null;
    }

    $parts = [];
    foreach (explode('/', $path) as $part) {
        if ($part === '' || $part === '.') {
            continue;
        }
        if ($part === '..') {
            return null;
        }
        $parts[] = $part;
    }
    return $parts === [] ? null : implode('/', $parts);
}

function inventory_album_path(string $relativePath, string $albumRoot, bool $directory): ?string
{
    $relativePath = inventory_relative_path($relativePath);
    if ($relativePath === null) {
        return null;
    }

    $candidate = realpath($albumRoot . DIRECTORY_SEPARATOR . str_replace('/', DIRECTORY_SEPARATOR, $relativePath));
    if ($candidate === false || !inventory_inside_root($candidate, $albumRoot)) {
        return null;
    }
    if ($directory ? !is_dir($candidate) : !is_file($candidate)) {
        return null;
    }

    return str_replace(DIRECTORY_SEPARATOR, '/', substr($candidate, strlen($albumRoot) + 1));
}

function inventory_photo_reference(string $reference, string $albumRoot): ?string
{
    $reference = html_entity_decode(trim($reference), ENT_QUOTES | ENT_HTML5, 'UTF-8');
    if ($reference === '' || str_contains($reference, "\0")) {
        return null;
    }

    $urlPath = parse_url($reference, PHP_URL_PATH);
    if (!is_string($urlPath)) {
        return null;
    }
    $urlPath = rawurldecode($urlPath);
    $marker = '/images/albums/';
    $position = strpos('/' . ltrim($urlPath, '/'), $marker);
    if ($position === false) {
        return null;
    }

    $relativePath = substr('/' . ltrim($urlPath, '/'), $position + strlen($marker));
    $canonical = inventory_album_path($relativePath, $albumRoot, false);
    if ($canonical === null) {
        return null;
    }
    $extension = strtolower(pathinfo($canonical, PATHINFO_EXTENSION));
    return in_array($extension, ['avif', 'gif', 'jpeg', 'jpg', 'png', 'webp'], true)
        ? $canonical
        : null;
}

function inventory_article_photos(string $html, string $albumRoot): array
{
    $photos = [];
    if (preg_match_all('/<img\b[^>]*>/is', $html, $images) !== false) {
        foreach ($images[0] as $imageTag) {
            if (preg_match_all(
                '/\b(src|data-src|data-original|srcset)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))/i',
                $imageTag,
                $attributes,
                PREG_SET_ORDER
            ) === false) {
                continue;
            }
            foreach ($attributes as $attribute) {
                $value = $attribute[2] !== '' ? $attribute[2] : ($attribute[3] !== '' ? $attribute[3] : ($attribute[4] ?? ''));
                $values = strtolower($attribute[1]) === 'srcset'
                    ? array_map(static fn(string $item): string => (string) preg_split('/\s+/', trim($item))[0], explode(',', $value))
                    : [$value];
                foreach ($values as $reference) {
                    $path = inventory_photo_reference($reference, $albumRoot);
                    if ($path !== null) {
                        $photos[$path] = ['type' => 'article', 'path' => $path];
                    }
                }
            }
        }
    }
    return $photos;
}

function inventory_gallery_photos(string $galleryPath, string $albumRoot): array
{
    $photos = [];
    $canonicalDirectory = inventory_album_path($galleryPath, $albumRoot, true);
    if ($canonicalDirectory === null) {
        return $photos;
    }

    $directoryPath = $albumRoot . DIRECTORY_SEPARATOR
        . str_replace('/', DIRECTORY_SEPARATOR, $canonicalDirectory);
    try {
        $iterator = new RecursiveIteratorIterator(
            new RecursiveDirectoryIterator($directoryPath, FilesystemIterator::SKIP_DOTS)
        );
        foreach ($iterator as $entry) {
            if (!$entry->isFile()) {
                continue;
            }
            $absolutePath = $entry->getRealPath();
            if ($absolutePath === false || !inventory_inside_root($absolutePath, $albumRoot)) {
                continue;
            }
            $path = str_replace(DIRECTORY_SEPARATOR, '/', substr($absolutePath, strlen($albumRoot) + 1));
            $extension = strtolower(pathinfo($path, PATHINFO_EXTENSION));
            if (in_array($extension, ['avif', 'gif', 'jpeg', 'jpg', 'png', 'webp'], true)) {
                $photos[$path] = ['type' => 'gallery', 'path' => $path];
            }
        }
    } catch (Throwable) {
        return $photos;
    }
    return $photos;
}

try {
    [$db, $prefix] = ws_database();
    $sql = 'SELECT c.id, c.title, c.created, c.introtext, c.`fulltext` '
         . 'FROM `' . $prefix . 'content` AS c WHERE c.id = ? LIMIT 1';
    $stmt = $db->prepare($sql);
    $stmt->bind_param('i', $articleId);
    $stmt->execute();
    $stmt->bind_result($id, $title, $created, $introtext, $fulltext);
    if (!$stmt->fetch()) {
        $stmt->close();
        $db->close();
        ws_json_response(['error' => 'Article not found'], 404);
    }
    $content = (string) $introtext . "\n" . (string) $fulltext;
    $stmt->close();
    $db->close();

    $config = new JConfig();
    $siteBase = trim((string) ($config->live_site ?? ''));
    if ($siteBase === '') {
        $siteBase = 'https://www.grimperoots.fr/j6';
    }
    $siteBase = rtrim($siteBase, '/');

    $albumRoot = realpath(dirname(__DIR__) . '/j6/images/albums');
    if ($albumRoot === false || !is_dir($albumRoot)) {
        throw new RuntimeException('Album directory unavailable');
    }

    $galleries = [];
    if (preg_match_all('/\{gallery\}\s*([^{}]*?)\s*\{\/gallery\}/i', $content, $matches) !== false) {
        foreach ($matches[1] as $galleryReference) {
            $galleryReference = trim(html_entity_decode($galleryReference, ENT_QUOTES | ENT_HTML5, 'UTF-8'));
            $gallery = inventory_relative_path($galleryReference);
            if ($gallery !== null) {
                $gallery = inventory_album_path($gallery, $albumRoot, true) ?? $gallery;
                $galleries[$gallery] = $gallery;
            }
        }
    }
    ksort($galleries, SORT_STRING);

    $photos = inventory_article_photos($content, $albumRoot);
    foreach ($galleries as $gallery) {
        foreach (inventory_gallery_photos($gallery, $albumRoot) as $path => $photo) {
            if (!isset($photos[$path])) {
                $photos[$path] = $photo;
            }
        }
    }
    ksort($photos, SORT_STRING);

    $article = [
        'article_id' => (int) $id,
        'article_title' => (string) $title,
        'article_date' => substr((string) $created, 0, 10),
        'article_url' => $siteBase . '/' . (int) $id,
        'galleries' => array_values($galleries),
        'photos' => array_values($photos),
    ];
} catch (Throwable $error) {
    error_log(sprintf(
        'article-photos.php failed for article %d: %s in %s:%d',
        $articleId,
        $error->getMessage(),
        basename($error->getFile()),
        $error->getLine()
    ));
    ws_json_response(['error' => 'Article photo inventory failed'], 500);
}

ws_json_response($article);
