from __future__ import annotations

import argparse
import os

import pandas as pd
import pymongo


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the training collection from a local CSV file")
    parser.add_argument(
        "--file",
        required=True,
        help="path to a compatible CSV that you are permitted to use",
    )
    parser.add_argument(
        "--database",
        default=os.getenv("DATA_INGESTION_DATABASE_NAME", "networksecurity"),
    )
    parser.add_argument(
        "--collection",
        default=os.getenv("DATA_INGESTION_COLLECTION_NAME", "network_events"),
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="delete existing collection contents before insert",
    )
    args = parser.parse_args()

    mongo_uri = os.getenv("MONGO_DB_URL")
    if not mongo_uri:
        raise SystemExit("MONGO_DB_URL must be configured in the environment")

    dataframe = pd.read_csv(args.file)
    records = dataframe.where(pd.notnull(dataframe), None).to_dict(orient="records")
    if not records:
        raise SystemExit("input CSV contains no rows")

    client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        collection = client[args.database][args.collection]
        if args.replace:
            collection.delete_many({})
        result = collection.insert_many(records, ordered=False)
        print(f"inserted={len(result.inserted_ids)} database={args.database} collection={args.collection}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
