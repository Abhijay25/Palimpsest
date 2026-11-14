<?php
// Per-language settings appended after MediaWiki's generated installer config.
$wgLanguageCode = getenv('MW_LANG') ?: $wgLanguageCode;
$wgLocaltimezone = 'UTC';
$wgDefaultSkin = 'vector-2022';
$wgVectorDefaultSkinVersion = '2'; // Vector 2022
$wgLogos = [
    '1x' => '/palimpsest-logo.svg',
    'icon' => '/palimpsest-icon.svg',
    'wordmark' => [
        'src' => '/palimpsest-logo.svg',
        'width' => 172,
        'height' => 36,
    ],
];
$wgEnableUploads = true;
$wgUploadDirectory = '/var/www/html/images';
$wgUseInstantCommons = true;
$wgJobRunRate = 0;
$wgEnableEmail = false;
$wgAllowUserSkin = true;
$wgRightsText = 'Wikipedia-derived content is available under CC BY-SA 4.0';
$wgRightsUrl = 'https://creativecommons.org/licenses/by-sa/4.0/';

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

// Link to the source project without guessing a source page from a local title.
$wgHooks['SkinAddFooterLinks'][] = static function ( $skin, $key, &$footerlinks ) {
    if ( $key === 'places' ) {
        $footerlinks['palimpsest-source'] = \MediaWiki\Html\Html::rawElement(
            'a',
            [ 'href' => 'https://www.wikipedia.org/', 'rel' => 'noreferrer noopener' ],
            'Wikipedia source project'
        );
    }
    return true;
};
