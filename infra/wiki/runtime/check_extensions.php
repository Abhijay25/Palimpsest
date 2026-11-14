<?php
declare(strict_types=1);

$extensions = [
    'Cite', 'DiscussionTools', 'Echo', 'Linter', 'ParserFunctions', 'Scribunto',
    'TemplateData', 'TemplateStyles', 'VisualEditor', 'WikiEditor',
];
$enabledDependencies = [
    'DiscussionTools' => ['VisualEditor', 'Linter', 'Echo'],
];
$skins = ['Vector'];
$errors = [];
$inventory = [];
$root = '/var/www/html';
$versionFile = "$root/includes/Defines.php";
if (!is_file($versionFile)) {
    fwrite(STDERR, "MediaWiki core files are missing from the image.\n");
    exit(1);
}

foreach ($extensions as $name) {
    $manifestPath = "$root/extensions/$name/extension.json";
    if (!is_file($manifestPath)) {
        $errors[] = "Missing bundled extension $name ($manifestPath)";
        continue;
    }
    $manifest = json_decode((string)file_get_contents($manifestPath), true);
    if (!is_array($manifest)) {
        $errors[] = "Invalid extension manifest for $name";
        continue;
    }
    if (($manifest['name'] ?? null) !== $name) {
        $errors[] = "$name manifest declares a different extension name";
    }
    foreach (($manifest['requires']['extensions'] ?? []) as $dependency => $_constraint) {
        if (!in_array($dependency, $extensions, true)) {
            $errors[] = "$name requires unenabled extension $dependency";
        }
    }
    foreach (($enabledDependencies[$name] ?? []) as $dependency) {
        if (!in_array($dependency, $extensions, true)) {
            $errors[] = "$name runtime configuration requires unenabled extension $dependency";
        }
    }
    $inventory[$name] = [
        'version' => $manifest['version'] ?? null,
        'mediawiki_constraint' => $manifest['requires']['MediaWiki'] ?? null,
        'extension_constraints' => $manifest['requires']['extensions'] ?? new stdClass(),
        'enabled_dependencies' => $enabledDependencies[$name] ?? [],
    ];
}
foreach ($skins as $name) {
    if (!is_file("$root/skins/$name/skin.json")) {
        $errors[] = "Missing bundled skin $name";
    }
}
if (!extension_loaded('mysqli')) {
    $errors[] = 'PHP mysqli extension is missing';
}
if (!extension_loaded('luasandbox')) {
    $errors[] = 'PHP LuaSandbox extension is missing (required by Scribunto)';
}
if (!is_dir("$root/vendor/wikimedia/parsoid")) {
    $errors[] = 'Bundled Parsoid library is missing (required for VisualEditor integration)';
}
$defines = (string)file_get_contents($versionFile);
if (!preg_match("/define\\s*\\(\\s*['\"]MW_VERSION['\"]\\s*,\\s*['\"]([^'\"]+)['\"]\\s*\\)/", $defines, $versionMatch)) {
    $errors[] = 'Could not read the MediaWiki core version from includes/Defines.php';
    $coreVersion = 'unknown';
} else {
    $coreVersion = $versionMatch[1];
}
if ($coreVersion !== '1.46.2') {
    $errors[] = "Expected MediaWiki 1.46.2, found $coreVersion";
}
foreach ($inventory as $name => &$details) {
    $details['bundled_with_mediawiki'] = $coreVersion;
    $constraint = $details['mediawiki_constraint'];
    $compatible = true;
    if (is_string($constraint) && trim($constraint) !== '' && $constraint !== '*') {
        $alternatives = preg_split('/\\s*\\|\\|\\s*/', trim($constraint)) ?: [];
        $compatible = false;
        foreach ($alternatives as $alternative) {
            $checks = preg_split('/\\s*,\\s*|\\s+(?=[<>=~^])/', trim($alternative)) ?: [];
            $alternativeOk = true;
            foreach ($checks as $check) {
                if (!preg_match('/^(>=|<=|>|<|=|\\^|~)?\\s*([0-9]+\\.[0-9]+(?:\\.[0-9]+)?)/', trim($check), $parts)) {
                    $errors[] = "$name has unsupported MediaWiki version constraint '$constraint'";
                    $alternativeOk = false;
                    break;
                }
                $operator = $parts[1] ?? '';
                $required = $parts[2];
                $cmp = version_compare($coreVersion, $required);
                $ok = match ($operator) {
                    '>=' => $cmp >= 0, '>' => $cmp > 0, '<=' => $cmp <= 0, '<' => $cmp < 0,
                    '=' => $cmp === 0,
                    '^' => $cmp >= 0 && (int)explode('.', $coreVersion)[0] === (int)explode('.', $required)[0],
                    '~' => $cmp >= 0 && array_slice(explode('.', $coreVersion), 0, 2) === array_slice(explode('.', $required), 0, 2),
                    default => $cmp === 0,
                };
                $alternativeOk = $alternativeOk && $ok;
            }
            $compatible = $compatible || $alternativeOk;
        }
    }
    $details['mediawiki_compatible'] = $compatible;
    if (!$compatible) {
        $errors[] = "$name requires MediaWiki '$constraint', incompatible with $coreVersion";
    }
}
unset($details);
if ($errors) {
    fwrite(STDERR, implode("\n", $errors) . "\n");
    exit(1);
}
fwrite(STDOUT, json_encode([
    'mediawiki_version' => $coreVersion,
    'extensions' => $inventory,
    'skins' => ['Vector' => ['version' => json_decode((string)file_get_contents("$root/skins/Vector/skin.json"), true)['version'] ?? null, 'default_version' => '2']],
    'integrations' => ['Parsoid' => ['status' => 'bundled', 'path' => 'vendor/wikimedia/parsoid']],
    'dependency_check' => 'passed',
], JSON_UNESCAPED_SLASHES) . "\n");
