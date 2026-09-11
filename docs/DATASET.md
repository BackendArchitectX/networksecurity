# Dataset contract and provenance

## Why the original CSV is not redistributed

This repository originally contained a phishing-classification CSV, but its source and redistribution license were not documented well enough to verify that republishing the raw file was permitted. The dataset has therefore been removed from the current tree rather than guessing at provenance or licensing.

The backend architecture does not depend on a specific downloadable dataset. Training reads records from MongoDB and validates them against `data_schema/schema.yaml`.

## Expected schema

The current workload expects the feature columns declared in `data_schema/schema.yaml` plus the target column `Result`. Training validation rejects missing, unexpected, duplicate, empty or non-numeric feature data before model selection.

The target values are normalized by the transformation pipeline from the source classification encoding into the binary labels consumed by the classifiers. Review `data_schema/schema.yaml` and `networksecurity/components/data_transformation.py` before importing a replacement dataset.

## Supplying training data

Use a dataset that you are legally permitted to use and redistribute. Keep the raw file outside this repository unless its license clearly permits inclusion.

Seed a compatible CSV into MongoDB with:

```bash
export MONGO_DB_URL='mongodb://...'
python scripts/seed_mongodb.py --file /path/to/your/phishing-data.csv --replace
```

The default database and collection are `networksecurity.network_events`; both can be overridden with environment variables or command-line options.

## Reproducibility metadata to record for a real dataset

For a production or research release, record at least:

- canonical source URL;
- dataset author or organization;
- version / retrieval date;
- license and redistribution terms;
- checksum of the exact source artifact;
- feature and target definitions;
- transformations applied before ingestion;
- train/test split policy and random seed;
- known sampling, labeling and class-balance limitations.

This project deliberately does not invent those details for the removed historical CSV.
