from __future__ import annotations

import logging
import os
import socket
import threading
import uuid
from typing import Callable

from networksecurity.config.runtime import RuntimeSettings
from networksecurity.pipeline.training_pipeline import TrainingPipeline
from networksecurity.services.training_jobs import (
    TrainingJob,
    TrainingJobLeaseError,
    TrainingJobStore,
)


LOG = logging.getLogger(__name__)


class TrainingWorker:
    """Executes durable training jobs outside the serving process."""

    def __init__(
        self,
        settings: RuntimeSettings,
        *,
        worker_id: str | None = None,
        pipeline_factory: Callable[[], TrainingPipeline] | None = None,
    ):
        self._settings = settings
        self._worker_id = worker_id or _default_worker_id()
        self._store = TrainingJobStore(
            settings.training_job_db_path,
            max_pending_jobs=settings.max_pending_training_jobs,
            max_attempts=settings.training_job_max_attempts,
        )
        self._pipeline_factory = pipeline_factory or (lambda: TrainingPipeline(settings))

    @property
    def worker_id(self) -> str:
        return self._worker_id

    def run_once(self) -> bool:
        job = self._store.claim_next(
            self._worker_id,
            lease_seconds=self._settings.training_job_lease_seconds,
        )
        if job is None:
            return False
        self._execute(job)
        return True

    def run_forever(self, stop_event: threading.Event, poll_interval_seconds: float = 1.0) -> None:
        LOG.info("training worker started", extra={"worker_id": self._worker_id})
        while not stop_event.is_set():
            worked = self.run_once()
            if not worked:
                stop_event.wait(poll_interval_seconds)
        LOG.info("training worker stopped", extra={"worker_id": self._worker_id})

    def _execute(self, job: TrainingJob) -> None:
        if job.fence_token is None:
            raise TrainingJobLeaseError("claimed job is missing fencing token")

        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            args=(job.job_id, job.fence_token, heartbeat_stop),
            daemon=True,
            name=f"lease-{job.job_id}",
        )
        heartbeat.start()
        pipeline = self._pipeline_factory()

        try:
            candidate = pipeline.prepare_candidate()

            # Training is complete. Stop heartbeats before entering the short fenced
            # promotion transaction; claim/reclaim cannot proceed while it holds the
            # SQLite write lock.
            heartbeat_stop.set()
            heartbeat.join(timeout=2)

            bundle = self._store.promote_owned(
                job_id=job.job_id,
                worker_id=self._worker_id,
                fence_token=job.fence_token,
                model_version=candidate.model_version,
                promote=lambda token: pipeline.promote_candidate(candidate, token),
            )
            LOG.info(
                "training job promoted",
                extra={"job_id": job.job_id, "model_version": bundle.version},
            )

            try:
                pipeline.mirror_promoted(bundle)
            except Exception:
                # Remote mirroring is explicitly non-authoritative. A mirror outage
                # must not roll back an already committed local promotion.
                LOG.exception(
                    "model mirror failed after local promotion",
                    extra={"job_id": job.job_id, "model_version": bundle.version},
                )
        except TrainingJobLeaseError:
            LOG.warning(
                "training result discarded because worker lost lease ownership",
                extra={"job_id": job.job_id, "worker_id": self._worker_id},
            )
        except Exception as exc:
            try:
                self._store.fail(
                    job.job_id,
                    self._worker_id,
                    job.fence_token,
                    f"{type(exc).__name__}: {exc}",
                )
            except TrainingJobLeaseError:
                LOG.warning(
                    "training failed after lease ownership was lost; state left to current owner",
                    extra={"job_id": job.job_id, "worker_id": self._worker_id},
                )
            LOG.exception("training job failed", extra={"job_id": job.job_id})
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=2)

    def _heartbeat_loop(
        self,
        job_id: str,
        fence_token: int,
        stop_event: threading.Event,
    ) -> None:
        interval = max(1.0, self._settings.training_job_lease_seconds / 3)
        while not stop_event.wait(interval):
            try:
                self._store.heartbeat(
                    job_id,
                    self._worker_id,
                    fence_token,
                    lease_seconds=self._settings.training_job_lease_seconds,
                )
            except TrainingJobLeaseError:
                LOG.warning(
                    "training job heartbeat lost lease ownership",
                    extra={"job_id": job_id, "worker_id": self._worker_id},
                )
                return
            except Exception:
                LOG.exception("training job heartbeat failed", extra={"job_id": job_id})
                return


def _default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
