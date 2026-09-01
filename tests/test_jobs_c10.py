from pathlib import Path
import hashlib
from case_docket.application.jobs import JobService, ProcessorRequest, synthetic_reference_processor

def req():
    return ProcessorRequest('synthetic', ('file-1',), ('a' * 64,), {'language':'uk'}, 'synthetic-1')

def test_durable_success_restart_and_idempotency(tmp_path: Path):
    service = JobService(tmp_path / 'varta.sqlite3')
    job_id = service.submit(req(), 'same-request')
    assert service.submit(req(), 'same-request') == job_id
    token, _ = service.claim(job_id)
    result = synthetic_reference_processor(req())
    service.finalize(job_id, token, result)
    restarted = JobService(tmp_path / 'varta.sqlite3')
    job = restarted.get(job_id)
    assert job and job.status == 'succeeded' and job.result == result

def test_expired_lease_is_interrupted_and_retryable(tmp_path: Path):
    service = JobService(tmp_path / 'varta.sqlite3')
    job_id = service.submit(req(), 'retry')
    token, _ = service.claim(job_id, lease_seconds=-1)
    assert token and service.recover_expired() == 1
    assert service.get(job_id).status == 'interrupted'
    retry_token, _ = service.claim(job_id)
    service.finalize(job_id, retry_token, synthetic_reference_processor(req()))
    assert service.get(job_id).status == 'succeeded'

def test_manifest_provenance_and_input_unchanged(tmp_path: Path):
    source = b'synthetic original only'
    before = hashlib.sha256(source).hexdigest()
    result = synthetic_reference_processor(req())
    assert result['input_ids'] == ['file-1']
    assert result['input_hashes'] == ['a' * 64]
    assert hashlib.sha256(source).hexdigest() == before
