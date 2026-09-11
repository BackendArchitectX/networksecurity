from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import statistics
import time

import httpx


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, round((len(ordered) - 1) * p))
    return ordered[index]


def one_request(client: httpx.Client, url: str, payload: dict) -> tuple[int, float]:
    started = time.perf_counter()
    response = client.post(url, json=payload)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return response.status_code, elapsed_ms


def main() -> None:
    parser = argparse.ArgumentParser(description="Small reproducible HTTP benchmark for the prediction API")
    parser.add_argument("--url", default="http://127.0.0.1:8080/api/v1/predict")
    parser.add_argument("--request-file", default="examples/predict-request.json")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=16)
    args = parser.parse_args()

    with open(args.request_file, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    latencies: list[float] = []
    statuses: dict[int, int] = {}
    started = time.perf_counter()

    limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)
    with httpx.Client(timeout=10, limits=limits) as client:
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = [executor.submit(one_request, client, args.url, payload) for _ in range(args.requests)]
            for future in as_completed(futures):
                status_code, latency_ms = future.result()
                statuses[status_code] = statuses.get(status_code, 0) + 1
                latencies.append(latency_ms)

    elapsed = time.perf_counter() - started
    result = {
        "requests": args.requests,
        "concurrency": args.concurrency,
        "elapsed_seconds": round(elapsed, 3),
        "throughput_rps": round(args.requests / elapsed, 2),
        "latency_ms": {
            "mean": round(statistics.mean(latencies), 3),
            "p50": round(percentile(latencies, 0.50), 3),
            "p95": round(percentile(latencies, 0.95), 3),
            "p99": round(percentile(latencies, 0.99), 3),
        },
        "status_counts": statuses,
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
