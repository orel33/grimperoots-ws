<?php
declare(strict_types=1);

require_once __DIR__ . '/_common.php';

ws_require_get();
ws_require_token();

$articleId = filter_input(INPUT_GET, 'id', FILTER_VALIDATE_INT);
if ($articleId === false || $articleId === null || $articleId <= 0) {
    ws_json_response(['error' => 'Invalid id'], 400);
}

try {
    [$db, $prefix] = ws_database();
    $sql = 'SELECT c.id, c.title, c.alias, c.catid AS category_id, '
         . 'cat.title AS category, c.created, c.introtext, c.fulltext '
         . 'FROM `' . $prefix . 'content` AS c '
         . 'LEFT JOIN `' . $prefix . 'categories` AS cat ON cat.id = c.catid '
         . 'WHERE c.id = ? LIMIT 1';
    $stmt = $db->prepare($sql);
    $stmt->bind_param('i', $articleId);
    $stmt->execute();
    $stmt->bind_result($id, $title, $alias, $categoryId, $category, $created, $introtext, $fulltext);
    if (!$stmt->fetch()) {
        $stmt->close();
        $db->close();
        ws_json_response(['error' => 'Article not found'], 404);
    }
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
    while ($tagStmt->fetch()) {
        $article['existing_tags'][] = (int) $tagId;
    }
    $tagStmt->close();
    $db->close();
} catch (Throwable $error) {
    ws_json_response(['error' => 'Article lookup failed'], 500);
}

ws_json_response($article);
