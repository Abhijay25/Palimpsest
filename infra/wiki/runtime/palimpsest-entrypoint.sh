#!/bin/sh
set -eu

if [ ! -r /etc/palimpsest/LocalSettings.php ]; then
    echo "Palimpsest runtime config is missing or unreadable for ${MW_LANG:-unknown}." >&2
    exit 1
fi

# Keep credential-bearing settings private on the host and readable only by the wiki group in-container.
cp /etc/palimpsest/LocalSettings.php /var/www/html/LocalSettings.php
chown root:www-data /var/www/html/LocalSettings.php
chmod 0640 /var/www/html/LocalSettings.php

# ResourceLoader debug styles use the extension's public asset URL. Keep the
# code mounted read-only while exposing the standard extension asset paths.
for extension in PalimpsestBlame PalimpsestFlags PalimpsestIssues; do
    if [ -d "/opt/palimpsest/extensions/$extension" ] && [ ! -e "/var/www/html/extensions/$extension" ]; then
        ln -s "/opt/palimpsest/extensions/$extension" "/var/www/html/extensions/$extension"
    fi
done

exec /usr/local/bin/docker-php-entrypoint "$@"
