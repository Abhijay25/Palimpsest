CREATE TABLE /*_*/palimpsestblame_job_revision (
	pbjr_job_id VARBINARY(32) NOT NULL,
	pbjr_page_id INT UNSIGNED NOT NULL,
	pbjr_revision_id BIGINT UNSIGNED NOT NULL,
	pbjr_order INT UNSIGNED NOT NULL,
	pbjr_sha256 VARBINARY(64) NOT NULL,
	pbjr_text MEDIUMBLOB NOT NULL,
	PRIMARY KEY (pbjr_job_id, pbjr_revision_id),
	UNIQUE KEY pbjr_job_order (pbjr_job_id, pbjr_order),
	KEY pbjr_page_revision (pbjr_page_id, pbjr_revision_id)
) /*$wgDBTableOptions*/;
