#!/bin/sh
# Runs in the digest-pinned MediaWiki image, where installer output is writable.
set -eu

settings=/tmp/palimpsest-config/LocalSettings.php
managed=/tmp/palimpsest-config/runtime-settings.php
[ -f "$settings" ] || { echo "missing installer settings" >&2; exit 1; }

# The runtime include owns these bundled extension/skin loads.
sed -i -E "/^[[:space:]]*wfLoad(Skin|Extension)\([[:space:]]*['\"](Cite|ParserFunctions|Scribunto|TemplateData|TemplateStyles|Linter|Echo|VisualEditor|WikiEditor|DiscussionTools|MultimediaViewer|PageImages|TextExtracts|CiteThisPage|CategoryTree|ImageMap|Poem|SyntaxHighlight_GeSHi|Vector)['\"][[:space:]]*\);[[:space:]]*$/d" "$settings"
grep -Fqx "require_once '/etc/palimpsest/runtime-settings.php';" "$settings" || printf "\nrequire_once '/etc/palimpsest/runtime-settings.php';\n" >> "$settings"
cp /usr/local/share/palimpsest/runtime-settings.php "$managed"

# LocalSettings contains database credentials.  The web server can read it, but
# unrelated host users cannot traverse this directory or read the file.
chown 33:33 /tmp/palimpsest-config "$settings" "$managed"
# Search-only access lets a later host-side setup verify the marker files without
# listing the directory or reading LocalSettings.php.
chmod 0751 /tmp/palimpsest-config
chmod 0640 "$settings"
chmod 0644 "$managed"
