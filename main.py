from __future__ import annotations

from networksecurity.pipeline.training_pipeline import TrainingPipeline


if __name__ == "__main__":
    artifact = TrainingPipeline().run_pipeline()
    print(artifact)
