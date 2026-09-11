from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
import sqlite3
import uuid
from typing import Any


class TrainingQueueFullError(RuntimeError):
    pass


class TrainingJobLeaseError(RuntimeError):
    pass


class TrainingJobState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class TrainingJob:
    job_id: str
    idempotency_key: str
    state: TrainingJobState
    submitted_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    worker_id: str | None = None
    lease_until: str | None = None
    attempts: int = 0
    model_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data


class TrainingJobStore:
    """Durable single-active-job queue with idempotency and lease recovery.

    SQLite is deliberately used as a reference durable store: API and worker may run
    in separate processes, duplicate submissions survive restarts, and abandoned
    RUNNING jobs can be reclaimed after their lease expires. `claim_next` enforces a
    single active training job across all workers so publication to the shared model
    registry has single-writer semantics.
    """

    def __init__(
        self,
        database_path: str,
        *,
        max_pending_jobs: int = 32,
        max_attempts: int = 3,
    ):
        if max_pending_jobs < 1:
            raise ValueError("max_pending_jobs must be at least 1")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._database_path = database_path
        self._max_pending_jobs = max_pending_jobs
        self._max_attempts = max_attempts
        parent = Path(database_path).parent
        if str(parent) not in {"", "."}:
            parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def submit(self, idempotency_key: str) -> tuple[TrainingJob, bool]:
        now = _utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM training_jobs WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                connection.commit()
                return _row_to_job(existing), False

            active_count = connection.execute(
                "SELECT COUNT(*) FROM training_jobs WHERE state IN (?, ?)",
                (TrainingJobState.QUEUED.value, TrainingJobState.RUNNING.value),
            ).fetchone()[0]
            if active_count >= self._max_pending_jobs:
                connection.rollback()
                raise TrainingQueueFullError("training queue capacity reached")

            job_id = f"train_{uuid.uuid4().hex}"
            connection.execute(
                """
                INSERT INTO training_jobs (
                    job_id, idempotency_key, state, submitted_at, attempts
                ) VALUES (?, ?, ?, ?, 0)
                """,
                (job_id, idempotency_key, TrainingJobState.QUEUED.value, now),
            )
            row = connection.execute(
                "SELECT * FROM training_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            connection.commit()
            return _row_to_job(row), True

    def get(self, job_id: str) -> TrainingJob | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM training_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return None if row is None else _row_to_job(row)

    def claim_next(self, worker_id: str, lease_seconds: int) -> TrainingJob | None:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")

        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        lease_until = (now_dt + timedelta(seconds=lease_seconds)).isoformat()

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._reclaim_expired_jobs(connection, now)

            # A shared filesystem registry is deliberately single-writer. Multiple
            # worker processes may compete for work, but only one may train/publish.
            running = connection.execute(
                "SELECT 1 FROM training_jobs WHERE state = ? LIMIT 1",
                (TrainingJobState.RUNNING.value,),
            ).fetchone()
            if running is not None:
                connection.commit()
                return None

            row = connection.execute(
                """
                SELECT * FROM training_jobs
                WHERE state = ?
                ORDER BY submitted_at ASC, job_id ASC
                LIMIT 1
                """,
                (TrainingJobState.QUEUED.value,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None

            job_id = row["job_id"]
            connection.execute(
                """
                UPDATE training_jobs
                SET state = ?,
                    started_at = COALESCE(started_at, ?),
                    worker_id = ?,
                    lease_until = ?,
                    attempts = attempts + 1
                WHERE job_id = ? AND state = ?
                """,
                (
                    TrainingJobState.RUNNING.value,
                    now,
                    worker_id,
                    lease_until,
                    job_id,
                    TrainingJobState.QUEUED.value,
                ),
            )
            claimed = connection.execute(
                "SELECT * FROM training_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            connection.commit()
            return _row_to_job(claimed)

    def heartbeat(self, job_id: str, worker_id: str, lease_seconds: int) -> None:
        lease_until = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE training_jobs
                SET lease_until = ?
                WHERE job_id = ? AND state = ? AND worker_id = ?
                """,
                (lease_until, job_id, TrainingJobState.RUNNING.value, worker_id),
            )
            if cursor.rowcount != 1:
                raise TrainingJobLeaseError("worker no longer owns training job lease")

    def succeed(self, job_id: str, worker_id: str, model_version: str) -> None:
        self._finish(
            job_id=job_id,
            worker_id=worker_id,
            state=TrainingJobState.SUCCEEDED,
            error=None,
            model_version=model_version,
        )

    def fail(self, job_id: str, worker_id: str, error: str) -> None:
        self._finish(
            job_id=job_id,
            worker_id=worker_id,
            state=TrainingJobState.FAILED,
            error=error[:2048],
            model_version=None,
        )

    def _reclaim_expired_jobs(self, connection: sqlite3.Connection, now: str) -> None:
        connection.execute(
            """
            UPDATE training_jobs
            SET state = ?, finished_at = ?, error = ?, worker_id = NULL, lease_until = NULL
            WHERE state = ? AND lease_until IS NOT NULL AND lease_until <= ? AND attempts >= ?
            """,
            (
                TrainingJobState.FAILED.value,
                now,
                "worker lease expired after maximum attempts",
                TrainingJobState.RUNNING.value,
                now,
                self._max_attempts,
            ),
        )
        connection.execute(
            """
            UPDATE training_jobs
            SET state = ?, worker_id = NULL, lease_until = NULL
            WHERE state = ? AND lease_until IS NOT NULL AND lease_until <= ? AND attempts < ?
            """,
            (
                TrainingJobState.QUEUED.value,
                TrainingJobState.RUNNING.value,
                now,
                self._max_attempts,
            ),
        )

    def _finish(
        self,
        *,
        job_id: str,
        worker_id: str,
        state: TrainingJobState,
        error: str | None,
        model_version: str | None,
    ) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE training_jobs
                SET state = ?, finished_at = ?, error = ?, model_version = ?,
                    worker_id = NULL, lease_until = NULL
                WHERE job_id = ? AND state = ? AND worker_id = ?
                """,
                (
                    state.value,
                    _utc_now(),
                    error,
                    model_version,
                    job_id,
                    TrainingJobState.RUNNING.value,
                    worker_id,
                ),
            )
            if cursor.rowcount != 1:
                raise TrainingJobLeaseError("worker no longer owns training job lease")

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS training_jobs (
                    job_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    error TEXT,
                    worker_id TEXT,
                    lease_until TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    model_version TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_training_jobs_state_submitted
                    ON training_jobs(state, submitted_at);
                CREATE INDEX IF NOT EXISTS idx_training_jobs_lease
                    ON training_jobs(state, lease_until);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection


def _row_to_job(row: sqlite3.Row) -> TrainingJob:
    return TrainingJob(
        job_id=row["job_id"],
        idempotency_key=row["idempotency_key"],
        state=TrainingJobState(row["state"]),
        submitted_at=row["submitted_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error=row["error"],
        worker_id=row["worker_id"],
        lease_until=row["lease_until"],
        attempts=int(row["attempts"]),
        model_version=row["model_version"],
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
