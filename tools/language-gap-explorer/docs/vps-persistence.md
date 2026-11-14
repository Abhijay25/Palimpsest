# Persisting the research app on a VPS

The vectors are database data, not files shipped with the application source. Snapshot embeddings live in `passage.embedding`; historical embeddings live in `divergence_vector.embedding`, with derived grouping features in `paired_feature`. Comparison runs, exact evidence, question labels, search documents, request caches and statement highlights are also stored in the research database, `language_gaps`.

The current research Compose configuration pins `mariadb:12.3.3` and mounts the named volume `gap_database` at `/var/lib/mysql`. Keep persistent database storage across application/container redeployments. Creating a fresh VPS volume does not copy the existing local database into it.

## Migration

1. Take a consistent logical backup of the local `language_gaps` database using `mariadb-dump`, or an appropriately prepared MariaDB physical backup. Transfer the backup privately and restore it on the VPS. Use the pinned database version for the first migration and verify the restored vector tables/index definitions. Do not copy a live database directory as an ordinary folder.
2. Preserve the research `data` directory, including cached historical source files and article-scoped manifests, on persistent VPS storage. These support repeatable acquisition, audit and resume.
3. Copy or explicitly install the model assets in `model-cache`. They are separate from the stored embedding vectors. Keep `intfloat/multilingual-e5-small` / 384 dimensions for queries against the existing vectors; installing its weights again does not require re-embedding the corpus. Local translations also require their configured model packages.
4. Set `NEOWIKI_RESEARCH_ROOT` to that persistent runtime directory on the VPS. Configure `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` and `DB_PASSWORD` for the deployed database. The hostname/port depends on whether the app runs on the host or shares the database container network.
5. Verify article/run counts, source links, vector search and cached question/evidence reads before enabling preparation workers. Keep regular backups in addition to the persistent volume.

Deploying this Git repository alone transfers code, not the ignored database, runtime caches, model assets or private environment configuration. Preserve the existing request cache/reservations when migrating so completed paid work is reused. Do not put backups or credentials in Git.

This document describes the migration; no VPS deployment or restore has been executed by this iteration.

References: [MariaDB container backup and restoration](https://mariadb.com/docs/server/server-management/automated-mariadb-deployment-and-administration/docker-and-mariadb/container-backup-and-restoration), [mariadb-dump](https://mariadb.com/docs/server/clients-and-utilities/backup-restore-and-import-clients/mariadb-dump).
