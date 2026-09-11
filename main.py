from __future__ import annotations

from datetime import datetime, timezone

from networksecurity.config.runtime import RuntimeSettings
from networksecurity.services.training_jobs import TrainingJobStore
from networksecurity.services.training_worker import TrainingWorker


if __name__ == "__main__":
    settings = RuntimeSettings.from_env()
    store = TrainingJobStore(
        settings.training_job_db_path,
        max_pending_jobs=settings.max_pending_training_jobs,
        max_attempts=settings.training_job_max_attempts,
    )
    idempotency_key = f"cli-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')}"
    job, _ = store.submit(idempotency_key)

    worker = TrainingWorker(settings, worker_id="cli-training-worker")
    worker.run_once()
    print(store.get(job.job_id))
