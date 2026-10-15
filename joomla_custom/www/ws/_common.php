<?php
declare(strict_types=1);

ini_set('display_errors', '0');
error_reporting(0);

function ws_json_response(array $payload, int $status = 200): never
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function ws_require_get(): void
{
    if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') {
        header('Allow: GET');
        ws_json_response(['error' => 'Method not allowed'], 405);
    }
}

function ws_require_token(): void
{
    $localConfig = __DIR__ . '/config.local.php';
    if (!is_file($localConfig)) {
        ws_json_response(['error' => 'Service unavailable'], 503);
    }

    require_once $localConfig;
    $expected = defined('GRIMPEROOTS_WS_TOKEN')
        ? (string) GRIMPEROOTS_WS_TOKEN
        : '';
    $provided = $_SERVER['HTTP_X_GRIMPEROOTS_TOKEN']
        ?? $_SERVER['REDIRECT_HTTP_X_GRIMPEROOTS_TOKEN']
        ?? '';
    if ($provided === '' && function_exists('getallheaders')) {
        foreach (getallheaders() as $name => $value) {
            if (strtolower((string) $name) === 'x-grimperoots-token') {
                $provided = (string) $value;
                break;
            }
        }
    }
    if ($expected === '' || $provided === '' || !hash_equals($expected, $provided)) {
        ws_json_response(['error' => 'Unauthorized'], 401);
    }
}

function ws_database(): array
{
    require_once dirname(__DIR__) . '/j6/configuration.php';
    $config = new JConfig();
    $prefix = (string) $config->dbprefix;
    if (!preg_match('/^[A-Za-z0-9_]+$/', $prefix)) {
        throw new RuntimeException('Invalid table prefix');
    }

    $port = isset($config->port) ? (int) $config->port : 3306;
    $db = new mysqli($config->host, $config->user, $config->password, $config->db, $port);
    $db->set_charset('utf8mb4');
    return [$db, $prefix];
}
