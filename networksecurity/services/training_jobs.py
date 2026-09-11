from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
import sqlite3
import uuid
from typing import Any, Callable, TypeVar


T = TypeVar("T")


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
    fence_token: int | None = None
    model_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data


class TrainingJobStore:
    """Durable single-active-job queue with leases and fencing tokens.

    Every successful claim receives a globally monotonic fence token. Lease-sensitive
    mutations require the exact `(job_id, worker_id, fence_token)` tuple and a lease
    that is still live. Promotion is executed while `BEGIN IMMEDIATE` holds the
    control-plane write lock, so a job cannot be reclaimed while its pointer update
    is being committed.
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

    def ensure_fence_at_least(self, value: int) -> None:
        """Prevent fence-token reuse after restoring/recreating the job database."""
        if value < 0:
            raise ValueError("fence value cannot be negative")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE training_job_fence
                SET value = CASE WHEN value < ? THEN ? ELSE value END
                WHERE singleton = 1
                """,
                (value, value),
            )
            connection.commit()

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

            connection.execute(
                "UPDATE training_job_fence SET value = value + 1 WHERE singleton = 1"
            )
            fence_token = int(
                connection.execute(
                    "SELECT value FROM training_job_fence WHERE singleton = 1"
                ).fetchone()[0]
            )

            job_id = row["job_id"]
            cursor = connection.execute(
                """
                UPDATE training_jobs
                SET state = ?,
                    started_at = COALESCE(started_at, ?),
                    worker_id = ?,
                    lease_until = ?,
                    attempts = attempts + 1,
                    fence_token = ?
                WHERE job_id = ? AND state = ?
                """,
                (
                    TrainingJobState.RUNNING.value,
                    now,
                    worker_id,
                    lease_until,
                    fence_token,
                    job_id,
                    TrainingJobState.QUEUED.value,
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise TrainingJobLeaseError("training job could not be claimed")

            claimed = connection.execute(
                "SELECT * FROM training_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            connection.commit()
            return _row_to_job(claimed)

    def heartbeat(
        self,
        job_id: str,
        worker_id: str,
        fence_token: int,
        lease_seconds: int,
    ) -> None:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")
        now = _utc_now()
        lease_until = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE training_jobs
                SET lease_until = ?
                WHERE job_id = ?
                  AND state = ?
                  AND worker_id = ?
                  AND fence_token = ?
                  AND lease_until IS NOT NULL
                  AND lease_until > ?
                """,
                (
                    lease_until,
                    job_id,
                    TrainingJobState.RUNNING.value,
                    worker_id,
                    fence_token,
                    now,
                ),
            )
            if cursor.rowcount != 1:
                raise TrainingJobLeaseError("worker no longer owns a live training job lease")

    def fail(self, job_id: str, worker_id: str, fence_token: int, error: str) -> None:
        self._finish(
            job_id=job_id,
            worker_id=worker_id,
            fence_token=fence_token,
            state=TrainingJobState.FAILED,
            error=error[:2048],
            model_version=None,
        )

    def promote_owned(
        self,
        *,
        job_id: str,
        worker_id: str,
        fence_token: int,
        promote: Callable[[int], T],
        model_version: str,
    ) -> T:
        """Promote while lease ownership is fenced against concurrent reclaim.

        The SQLite write transaction intentionally remains open during the small local
        pointer swap. `claim_next` also requires `BEGIN IMMEDIATE`, so another worker
        cannot reclaim the job between that ownership check and pointer promotion.
        """
        now = _utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM training_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            self._assert_live_owner(row, worker_id, fence_token, now)

            result = promote(fence_token)

            cursor = connection.execute(
                """
                UPDATE training_jobs
                SET state = ?, finished_at = ?, error = NULL, model_version = ?,
                    worker_id = NULL, lease_until = NULL
                WHERE job_id = ?
                  AND state = ?
                  AND worker_id = ?
                  AND fence_token = ?
                """,
                (
                    TrainingJobState.SUCCEEDED.value,
                    _utc_now(),
                    model_version,
                    job_id,
                    TrainingJobState.RUNNING.value,
                    worker_id,
                    fence_token,
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise TrainingJobLeaseError("training job ownership changed during promotion")
            connection.commit()
            return result

    def _finish(
        self,
        *,
        job_id: str,
        worker_id: str,
        fence_token: int,
        state: TrainingJobState,
        error: str | None,
        model_version: str | None,
    ) -> None:
        now = _utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE training_jobs
                SET state = ?, finished_at = ?, error = ?, model_version = ?,
                    worker_id = NULL, lease_until = NULL
                WHERE job_id = ?
                  AND state = ?
                  AND worker_id = ?
                  AND fence_token = ?
                  AND lease_until IS NOT NULL
                  AND lease_until > ?
                """,
                (
                    state.value,
                    now,
                    error,
                    model_version,
                    job_id,
                    TrainingJobState.RUNNING.value,
                    worker_id,
                    fence_token,
                    now,
                ),
            )
            if cursor.rowcount != 1:
                raise TrainingJobLeaseError("worker no longer owns a live training job lease")

    @staticmethod
    def _assert_live_owner(
        row: sqlite3.Row | None,
        worker_id: str,
        fence_token: int,
        now: str,
    ) -> None:
        if row is None:
            raise TrainingJobLeaseError("training job does not exist")
        if row["state"] != TrainingJobState.RUNNING.value:
            raise TrainingJobLeaseError("training job is not running")
        if row["worker_id"] != worker_id or row["fence_token"] != fence_token:
            raise TrainingJobLeaseError("worker does not own the training job fence")
        if row["lease_until"] is None or row["lease_until"] <= now:
            raise TrainingJobLeaseError("training job lease has expired")

    def _reclaim_expired_jobs(self, connection: sqlite3.Connection, now: str) -> None:
        connection.execute(
            """
            UPDATE training_jobs
            SET state = ?, finished_at = ?, error = ?, worker_id = NULL,
                lease_until = NULL, fence_token = NULL
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
            SET state = ?, worker_id = NULL, lease_until = NULL, fence_token = NULL
            WHERE state = ? AND lease_until IS NOT NULL AND lease_until <= ? AND attempts < ?
            """,
            (
                TrainingJobState.QUEUED.value,
                TrainingJobState.RUNNING.value,
                now,
                self._max_attempts,
            ),
        )

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
                    fence_token INTEGER,
                    model_version TEXT
                );
                CREATE TABLE IF NOT EXISTS training_job_fence (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    value INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO training_job_fence(singleton, value) VALUES (1, 0);
                CREATE INDEX IF NOT EXISTS idx_training_jobs_state_submitted
                    ON training_jobs(state, submitted_at);
                CREATE INDEX IF NOT EXISTS idx_training_jobs_lease
                    ON training_jobs(state, lease_until);
                """
            )
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(training_jobs)").fetchall()
            }
            if "fence_token" not in columns:
                connection.execute("ALTER TABLE training_jobs ADD COLUMN fence_token INTEGER")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection


def _row_to_job(row: sqlite3.Row) -> TrainingJob:
    fence_token = row["fence_token"]
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
        fence_token=None if fence_token is None else int(fence_token),
        model_version=row["model_version"],
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
