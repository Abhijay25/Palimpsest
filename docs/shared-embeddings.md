# Shared corpus embeddings

The deployed reader is [NeoWiki](https://neowiki.srv2161484.hstgr.cloud/explore). The shared database and query encoder are private services on that VPS, accessed through SSH. Both the real BGE query path and the original E5 hybrid search have been verified. Connection secrets are supplied privately; no credentials belong in this document or Git.

## Main Library article search (BGE-M3, 1024 dimensions)

This is separate from the research passage store below. Main's `apps/library` expects `library.library_articles` containing BGE-M3 article vectors. The locked dataset already publishes these vectors; import them on the VPS without computing them again:

```sh
nw --profile catalog run --rm catalog-seed
nw --profile catalog run --rm catalog-seed python deploy/seed_bge_catalog.py --lock /run/datasets.lock.json --all
nw --profile catalog run --rm catalog-seed python deploy/seed_bge_catalog.py --status
```

Here `nw` is the Compose alias in the deployment guide. Seed only the dedicated `library` database using `library_seed`; teammates should use a separate SELECT-only account. Each locked asset is checksum verified. Source page/revision/model/release and truncation metadata remain recorded. Articles without a Wikidata ID use an explicit source-page namespace (`fi:<page_id>`), never an invented Q ID. Seeding does not import MediaWiki histories or expand the Library's existing three-topic layout.

With the optional team database override, VPS MariaDB listens only on `127.0.0.1:3311`. Forward it through each teammate's own SSH access: `ssh -N -L 3311:127.0.0.1:3311 USER@VPS`. Do not distribute the deployment private key or publish the DB port. Update the private `${LIBRARY_DATA_ROOT}/config.json` `database` object to host `127.0.0.1`, port `3311`, database `library`, and the provided read-only credentials. Preserve `wikis` and the verified local catalog/provenance files. Main reads this JSON, not `DB_HOST` environment variables; `npm run setup` overwrites this config and must not be used to switch to the shared DB.

New semantic queries still require a BGE-M3 query encoder. Keep the existing local Ollama endpoint or tunnel the separately deployed private one; `model` must remain `bge-m3`. Do not send 384-dimensional E5 queries to this index. Source articles stored here do not establish that their histories are imported into the native wikis.

The optional `compose.ollama.yaml` provides that private encoder on VPS loopback `11435`; include this override, start `ollama`, then explicitly run `ollama pull bge-m3` inside it. Pin `NEOWIKI_OLLAMA_IMAGE` to the tested image digest in the private server config after pulling. Add `-L 11435:127.0.0.1:11435` to the SSH tunnel and set private config `ollama` to `http://127.0.0.1:11435`. CPU embedding requests are serialized; the imported corpus vectors are already computed.

The current VPS uses CPU-only `alpine/ollama@sha256:74307a9408b6edcfc3927eea3542180c7307158a00099a1718212d6e45c114cf`, a third-party repack, not an official Ollama image. Its Ollama0.40.15 executable was verified byte-identical to the official upstream release (SHA256 `5b8be7213d4ba3ba587bceaeed897ef39a09fc44c51e490c098aa31ba7b9d3cf`); provenance is archived on the VPS. This avoids the large GPU image whose CDN download timed out. BGE-M3 model manifest `7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab` is preserved in the persistent model volume. Real English/Finnish queries returned finite, normalized1024-dimensional vectors; a laptop→SSH→encoder→MariaDB query returned Winter War and related articles in3.8seconds. Timings depend on concurrent CPU work.

Main's search and related-article queries restrict candidates to its verified catalog source page/revision identities before top-k. Otherwise unrelated rows from the larger shared index could occupy all nine results and disappear when the UI rejects unimported topics. The broader corpus remains available for direct research SQL queries.

## Research passage matching (E5, 384 dimensions)

The explicit offline worker fills the existing MariaDB `passage` vector index for imported articles with at least two EN/FI/SV editions. Eligibility comes from the database (7,256 multilingual topics in the current import); it does not use `prepare.py`'s five-topic default. Historical `divergence_vector` records are independent and untouched.

From `tools/language-gap-explorer`, with DB settings and `NEOWIKI_RESEARCH_ROOT` pointing at the mounted research volume:

```sh
python deploy/embed_corpus.py --limit 5 --workers 1
python deploy/embed_corpus.py --status
python deploy/embed_corpus.py --all --workers 1
```

Run the pilot and inspect its JSON progress before explicitly starting `--all`. This worker needs a writable research DB and a **preseeded** `model-cache` containing the existing quantized `intfloat/multilingual-e5-small` export. It never downloads models, calls an inference provider or needs an API key. CPU execution uses one ONNX thread and one worker; embeddings retain the existing 384 dimensions, normalized mean pooling, 400-token source chunks and `query: ` prefix.

Progress is durable in `corpus_embedding_progress`, keyed by edition/model with source revision, text hash and chunking policy. `--limit` counts unfinished topics, so repeated bounded pilots advance past completed topics. Restart the same command after interruption. Compatible existing snapshot vectors (including the original 134 passages) are adopted/reused without re-embedding; partial editions embed only missing or stale chunks. A different existing model is a conflict, never silently overwritten. Each edition's changes and completion marker commit in one transaction; a source change during computation aborts publication. Failed editions retain their previous vectors and a sanitized error type for retry.

The worker stops when its research volume has less than 512 MiB free space. Monitor the MariaDB volume separately, especially when it is on another host. `--status` is read-only and expects a previously initialized progress table. No bulk run is triggered by page reads, container startup or importing this module.
