import time

import pytest

from networksecurity.services.training_jobs import (
    TrainingJobLeaseError,
    TrainingJobState,
    TrainingJobStore,
    TrainingQueueFullError,
)


def _complete(store, claim, version):
    assert claim.fence_token is not None
    return store.promote_owned(
        job_id=claim.job_id,
        worker_id=claim.worker_id,
        fence_token=claim.fence_token,
        model_version=version,
        promote=lambda token: {"promotion_token": token, "version": version},
    )


def test_idempotency_survives_store_recreation(tmp_path):
    database = tmp_path / "jobs.db"
    first_store = TrainingJobStore(str(database), max_pending_jobs=4)
    first, created = first_store.submit("stable-dataset-release-key")

    second_store = TrainingJobStore(str(database), max_pending_jobs=4)
    second, created_again = second_store.submit("stable-dataset-release-key")

    assert created is True
    assert created_again is False
    assert first.job_id == second.job_id
    assert second.state == TrainingJobState.QUEUED


def test_queue_capacity_is_persistently_enforced(tmp_path):
    store = TrainingJobStore(str(tmp_path / "jobs.db"), max_pending_jobs=1)
    store.submit("first-request")

    with pytest.raises(TrainingQueueFullError, match="capacity"):
        store.submit("second-request")


def test_only_one_worker_can_hold_active_training_lease(tmp_path):
    store = TrainingJobStore(str(tmp_path / "jobs.db"), max_pending_jobs=4)
    first, _ = store.submit("first-training")
    second, _ = store.submit("second-training")

    first_claim = store.claim_next("worker-a", lease_seconds=30)
    blocked_claim = store.claim_next("worker-b", lease_seconds=30)

    assert first_claim is not None
    assert first_claim.job_id == first.job_id
    assert first_claim.fence_token == 1
    assert blocked_claim is None

    _complete(store, first_claim, "model-v1")
    second_claim = store.claim_next("worker-b", lease_seconds=30)
    assert second_claim is not None
    assert second_claim.job_id == second.job_id
    assert second_claim.fence_token == 2


def test_expired_worker_lease_is_reclaimed_with_new_fence(tmp_path):
    store = TrainingJobStore(
        str(tmp_path / "jobs.db"),
        max_pending_jobs=4,
        max_attempts=3,
    )
    submitted, _ = store.submit("lease-recovery-request")
    first_claim = store.claim_next("worker-a", lease_seconds=1)

    assert first_claim is not None
    assert first_claim.job_id == submitted.job_id
    assert first_claim.state == TrainingJobState.RUNNING
    assert first_claim.attempts == 1
    assert first_claim.fence_token == 1

    time.sleep(1.05)
    second_claim = store.claim_next("worker-b", lease_seconds=5)

    assert second_claim is not None
    assert second_claim.job_id == submitted.job_id
    assert second_claim.state == TrainingJobState.RUNNING
    assert second_claim.worker_id == "worker-b"
    assert second_claim.attempts == 2
    assert second_claim.fence_token == 2

    _complete(store, second_claim, "model-v2")
    completed = store.get(second_claim.job_id)
    assert completed is not None
    assert completed.state == TrainingJobState.SUCCEEDED
    assert completed.model_version == "model-v2"


def test_stale_worker_cannot_promote_after_lease_reclaim(tmp_path):
    store = TrainingJobStore(str(tmp_path / "jobs.db"), max_attempts=3)
    submitted, _ = store.submit("stale-worker-request")
    stale = store.claim_next("worker-a", lease_seconds=1)
    assert stale is not None and stale.fence_token is not None

    time.sleep(1.05)
    current = store.claim_next("worker-b", lease_seconds=30)
    assert current is not None and current.fence_token is not None
    assert current.fence_token > stale.fence_token

    promoted = []
    with pytest.raises(TrainingJobLeaseError):
        store.promote_owned(
            job_id=submitted.job_id,
            worker_id="worker-a",
            fence_token=stale.fence_token,
            model_version="stale-model",
            promote=lambda token: promoted.append(token),
        )

    assert promoted == []
    _complete(store, current, "current-model")
