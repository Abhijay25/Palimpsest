<?php
// Per-language settings appended after MediaWiki's generated installer config.
$wgLanguageCode = getenv('MW_LANG') ?: $wgLanguageCode;
$wgLocaltimezone = 'UTC';
$wgDefaultSkin = 'vector';
$wgVectorDefaultSkinVersion = '2'; // Vector 2022
$wgEnableUploads = true;
$wgUploadDirectory = '/var/www/html/images';
$wgUseInstantCommons = true;
$wgJobRunRate = 0;
$wgEnableEmail = false;
$wgAllowUserSkin = true;

wfLoadSkin('Vector');
wfLoadExtension('WikiEditor');
wfLoadExtension('Cite');
wfLoadExtension('ParserFunctions');
wfLoadExtension('Scribunto');
wfLoadExtension('TemplateData');
wfLoadExtension('TemplateStyles');
wfLoadExtension('Linter');
wfLoadExtension('Echo');
wfLoadExtension('VisualEditor');
wfLoadExtension('DiscussionTools');

$wgVisualEditorEnableWikitext = true;
$wgDefaultUserOptions['visualeditor-editor'] = 'visualeditor';
$wgDiscussionToolsEnable = true;
$wgDiscussionToolsEnable2017Wikitext = true;
$wgDiscussionToolsBetaFeature = false;

// Optional developer extension mount. Tests may provide a load.php file here.
$testExtensionLoader = '/opt/palimpsest/extensions/load.php';
if (is_file($testExtensionLoader)) {
    require $testExtensionLoader;
}
