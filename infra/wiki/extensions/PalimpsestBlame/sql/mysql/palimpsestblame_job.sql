CREATE TABLE /*_*/palimpsestblame_job (
	pbj_id VARBINARY(32) NOT NULL,
	pbj_page_id INT UNSIGNED NOT NULL,
	pbj_revision_id BIGINT UNSIGNED NOT NULL,
	pbj_algorithm VARBINARY(32) NOT NULL,
	pbj_schema_version SMALLINT UNSIGNED NOT NULL,
	pbj_status VARBINARY(16) NOT NULL,
	pbj_processed INT UNSIGNED NOT NULL DEFAULT 0,
	pbj_total INT UNSIGNED DEFAULT NULL,
	pbj_state MEDIUMBLOB NOT NULL,
	pbj_result MEDIUMBLOB DEFAULT NULL,
	pbj_error VARBINARY(64) DEFAULT NULL,
	pbj_updated BINARY(14) NOT NULL,
	PRIMARY KEY (pbj_id),
	UNIQUE KEY pbj_cache (pbj_page_id, pbj_revision_id, pbj_algorithm, pbj_schema_version),
	KEY pbj_status_updated (pbj_status, pbj_updated)
) /*$wgDBTableOptions*/;
