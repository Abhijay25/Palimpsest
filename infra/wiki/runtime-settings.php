<?php
// Per-language settings appended after MediaWiki's generated installer config.
$wgLanguageCode = getenv('MW_LANG') ?: $wgLanguageCode;
$wgSitename = 'NeoWiki';
$wgLocaltimezone = 'UTC';
$wgDefaultSkin = 'vector-2022';
// Reader/editor defaults checked against Wikimedia production configuration.
// Saved personal preferences continue to take precedence.
$wgDefaultUserOptions = array_replace( $wgDefaultUserOptions ?? [], [
    'vector-font-size' => 1,
    'vector-theme' => 'day',
    'vector-limited-width' => 1,
    'usebetatoolbar' => 1,
    'watchdefault' => 0,
    'watchmoves' => 0,
    'watchrollback' => 0,
    'watchcreations' => 1,
    'watchlistdays' => 3,
    'rcdays' => 1,
    'usenewrc' => 0,
    'extendwatchlist' => 0,
    'thumbsize' => 5,
] );
$wgThumbnailSteps = [ 20, 40, 60, 120, 250, 330, 500, 960, 1280, 1920, 3840 ];
// MediaWiki 1.46 still uses ThumbLimits for the thumbnail preference selector.
$wgThumbLimits = $wgThumbnailSteps;
$wgGalleryOptions['imageWidth'] = $wgLanguageCode === 'sv' ? 150 : 120;
$wgGalleryOptions['imageHeight'] = $wgLanguageCode === 'sv' ? 150 : 120;
$wgVectorMaxWidthOptions = [
    'exclude' => [ 'mainpage' => true,
        'querystring' => [ 'action' => '(history|edit)', 'diff' => '.+' ],
        'namespaces' => [ NS_SPECIAL, NS_CATEGORY ],
    ],
    'include' => [ 'Special:Preferences', 'Special:Userlogin', 'Special:CreateAccount' ],
];
$wgLogos = [
    '1x' => '/wikipedia-logo.png',
    'icon' => '/wikipedia-logo.png',
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
wfLoadExtension('MultimediaViewer');
wfLoadExtension('PageImages');
wfLoadExtension('TextExtracts');
wfLoadExtension('CiteThisPage');
wfLoadExtension('CategoryTree');
wfLoadExtension('ImageMap');
wfLoadExtension('Poem');
wfLoadExtension('SyntaxHighlight_GeSHi');

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
