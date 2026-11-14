<?php
declare(strict_types=1);
$language = getenv('MW_LANG');
if (!is_string($language) || !in_array($language, ['fi', 'sv', 'en'], true)) {
    exit(1);
}
$url = 'http://127.0.0.1/api.php?action=query&meta=siteinfo&siprop=general&format=json';
$context = stream_context_create(['http' => ['timeout' => 3]]);
$body = @file_get_contents($url, false, $context);
$data = is_string($body) ? json_decode($body, true) : null;
$general = is_array($data) ? ($data['query']['general'] ?? null) : null;
if (!is_array($general) || ($general['lang'] ?? null) !== $language || !str_starts_with((string)($general['generator'] ?? ''), 'MediaWiki 1.46.')) {
    exit(1);
}
exit(0);
