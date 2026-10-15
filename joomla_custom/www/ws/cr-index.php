<?php
declare(strict_types=1);

require_once __DIR__ . '/_common.php';

ws_require_get();

try {
    [$db, $prefix] = ws_database();
    $categoryId = filter_input(INPUT_GET, 'category_id', FILTER_VALIDATE_INT);
    $categoryId = $categoryId === false || $categoryId === null ? 33 : $categoryId;
    if ($categoryId <= 0) {
        ws_json_response(['error' => 'Invalid category_id'], 400);
    }

    $sql = 'SELECT c.id, c.title, c.created '
         . 'FROM `' . $prefix . 'content` AS c '
         . 'INNER JOIN `' . $prefix . 'categories` AS cat ON cat.id = c.catid '
         . 'INNER JOIN `' . $prefix . 'categories` AS root ON root.id = ? '
         . "WHERE cat.extension = 'com_content' "
         . 'AND cat.lft >= root.lft AND cat.rgt <= root.rgt '
         . 'AND c.state = 1 '
         . 'ORDER BY c.created DESC, c.id DESC';
    $stmt = $db->prepare($sql);
    $stmt->bind_param('i', $categoryId);
    $stmt->execute();
    $stmt->bind_result($id, $title, $created);

    $articles = [];
    while ($stmt->fetch()) {
        $articles[] = [
            'id' => (int) $id,
            'title' => $title,
            'created' => $created,
            'url' => '../' . (int) $id,
        ];
    }
    $stmt->close();
    $db->close();
} catch (Throwable $error) {
    ws_json_response(['error' => 'CR index lookup failed'], 500);
}

$accept = $_SERVER['HTTP_ACCEPT'] ?? '';
if (str_contains($accept, 'text/html')) {
    header('Content-Type: text/html; charset=utf-8');
    header('Cache-Control: no-store');
    echo '<!doctype html><html lang="fr"><meta charset="utf-8">'
       . '<meta name="viewport" content="width=device-width, initial-scale=1">'
       . '<title>Index des comptes rendus Grimperoots</title>'
       . '<style>body{font:16px system-ui,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem}'
       . 'table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:.5rem;border-bottom:1px solid #ddd}'
       . 'th{position:sticky;top:0;background:#fff}</style>'
       . '<h1>Comptes rendus</h1><table><thead><tr><th>ID</th><th>Date</th><th>Titre</th></tr></thead><tbody>';
    foreach ($articles as $article) {
        echo '<tr><td>' . $article['id'] . '</td><td>'
           . htmlspecialchars((string) $article['created'], ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8')
           . '</td><td><a href="'
           . htmlspecialchars('../j6/' . $article['id'], ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8')
           . '">' . htmlspecialchars((string) $article['title'], ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8')
           . '</a></td></tr>';
    }
    echo '</tbody></table></html>';
    exit;
}

ws_json_response(['data' => $articles, 'meta' => ['count' => count($articles)]]);
