# PalimpsestFlags

Loads only for configured revision diff pages and sends the two readable wikitext revisions,
title, language, revision IDs, a fixed service label required by the API schema, and no user data
to the configured audit service. Results are cached server-side for one day (errors for 60 seconds).

Set `$wgPalimpsestFlagsApiUrl = 'http://host.docker.internal:8765';` for a host-run API.
Use `infra/wiki/compose.flags.override.yaml` with the normal compose invocation so wiki containers
can resolve that hostname.

Deferred from the proposal: scrollbar minimap, mobile bottom sheet (compact popover is used on
phones too), audit-history/Issues page, reply threads, and mutation/suggestion application.

## Linux hosts

- Host firewalls (for example NixOS's default) drop traffic from the Docker bridge to the host, so `host.docker.internal:8765` times out. Either allow the bridge interface in the firewall, or run the wiki container with host networking and the API on `127.0.0.1`.
- Verified live on 2026-11-14 against MediaWiki 1.46.2 (Vector 2022) with a host-networked container and the real API (Gemini judge): flags render beside the diff for English, Finnish and Swedish pages.
