-- C10 correction: explicit processing_jobs -> processing_runs linkage and
-- immutable lifecycle history. Migration 0011 remains unchanged.

ALTER TABLE processing_jobs
ADD COLUMN processing_run_id TEXT REFERENCES processing_runs(id) ON DELETE RESTRICT;

UPDATE processing_jobs
SET processing_run_id = id
WHERE processing_run_id IS NULL
  AND EXISTS (SELECT 1 FROM processing_runs WHERE processing_runs.id = processing_jobs.id);

CREATE UNIQUE INDEX idx_processing_jobs_run
    ON processing_jobs(processing_run_id)
    WHERE processing_run_id IS NOT NULL;

CREATE TRIGGER processing_jobs_require_run
BEFORE INSERT ON processing_jobs
WHEN NEW.processing_run_id IS NULL
  OR NOT EXISTS (
      SELECT 1 FROM processing_runs WHERE processing_runs.id = NEW.processing_run_id
  )
BEGIN
    SELECT RAISE(ABORT, 'processing job requires a processing run');
END;

CREATE TRIGGER processing_jobs_run_link_immutable
BEFORE UPDATE OF processing_run_id ON processing_jobs
WHEN NEW.processing_run_id IS NOT OLD.processing_run_id
BEGIN
    SELECT RAISE(ABORT, 'processing job run link is immutable');
END;

CREATE TRIGGER processing_job_events_no_update
BEFORE UPDATE ON processing_job_events
BEGIN
    SELECT RAISE(ABORT, 'processing job events are append-only');
END;

CREATE TRIGGER processing_job_events_no_delete
BEFORE DELETE ON processing_job_events
BEGIN
    SELECT RAISE(ABORT, 'processing job events are append-only');
END;
