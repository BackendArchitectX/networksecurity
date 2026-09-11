from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


FeatureRecord = dict[str, Optional[float]]


class PredictionRequest(BaseModel):
    features: FeatureRecord


class BatchPredictionRequest(BaseModel):
    records: list[FeatureRecord] = Field(min_length=1)


class PredictionItem(BaseModel):
    prediction: int
    confidence: float | None = None


class PredictionResponse(BaseModel):
    request_id: str
    model_version: str
    latency_ms: float
    result: PredictionItem


class BatchPredictionResponse(BaseModel):
    request_id: str
    model_version: str
    latency_ms: float
    results: list[PredictionItem]


class TrainingJobResponse(BaseModel):
    job_id: str
    state: str
    submitted_at: str
    started_at: str | None = None
    finished_at: str | None = None
    attempts: int
    model_version: str | None = None
    error: str | None = None
    deduplicated: bool = False
