from types import SimpleNamespace

from networksecurity.config.runtime import RuntimeSettings
from networksecurity.services.training_jobs import TrainingJobState, TrainingJobStore
from networksecurity.services.training_worker import TrainingWorker


class FakePipeline:
    def __init__(self):
        self.mirrored = []

    def prepare_candidate(self):
        return SimpleNamespace(model_version="published-v3")

    def promote_candidate(self, candidate, promotion_token):
        return SimpleNamespace(version=candidate.model_version, promotion_token=promotion_token)

    def mirror_promoted(self, bundle):
        self.mirrored.append(bundle.version)


class FailingPipeline:
    def prepare_candidate(self):
        raise RuntimeError("synthetic training failure")


def _settings(tmp_path) -> RuntimeSettings:
    return RuntimeSettings(
        training_job_db_path=str(tmp_path / "jobs.db"),
        model_registry_dir=str(tmp_path / "registry"),
        schema_path=str(tmp_path / "schema.yaml"),
        training_job_lease_seconds=30,
    )


def test_worker_claims_persisted_job_and_records_published_version(tmp_path):
    settings = _settings(tmp_path)
    store = TrainingJobStore(settings.training_job_db_path)
    submitted, _ = store.submit("worker-integration-request")
    pipeline = FakePipeline()

    worker = TrainingWorker(
        settings,
        worker_id="worker-test",
        pipeline_factory=lambda: pipeline,
    )
    assert worker.worker_id == "worker-test"
    assert worker.run_once() is True

    completed = store.get(submitted.job_id)
    assert completed is not None
    assert completed.state == TrainingJobState.SUCCEEDED
    assert completed.attempts == 1
    assert completed.fence_token == 1
    assert completed.model_version == "published-v3"
    assert pipeline.mirrored == ["published-v3"]


def test_worker_returns_false_when_queue_is_empty(tmp_path):
    worker = TrainingWorker(
        _settings(tmp_path),
        worker_id="idle-worker",
        pipeline_factory=FakePipeline,
    )

    assert worker.run_once() is False


def test_worker_records_pipeline_failure_without_losing_job_state(tmp_path):
    settings = _settings(tmp_path)
    store = TrainingJobStore(settings.training_job_db_path)
    submitted, _ = store.submit("failing-worker-request")

    worker = TrainingWorker(
        settings,
        worker_id="failing-worker",
        pipeline_factory=FailingPipeline,
    )
    assert worker.run_once() is True

    failed = store.get(submitted.job_id)
    assert failed is not None
    assert failed.state == TrainingJobState.FAILED
    assert failed.attempts == 1
    assert failed.fence_token == 1
    assert failed.model_version is None
    assert failed.error == "RuntimeError: synthetic training failure"
