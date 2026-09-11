from __future__ import annotations

import signal
import threading

from networksecurity.config.runtime import RuntimeSettings
from networksecurity.services.training_worker import TrainingWorker


stop_event = threading.Event()


def _stop(*_args) -> None:
    stop_event.set()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    settings = RuntimeSettings.from_env()
    TrainingWorker(settings).run_forever(stop_event)
