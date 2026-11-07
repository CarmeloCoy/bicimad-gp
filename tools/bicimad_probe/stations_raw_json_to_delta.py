import argparse
import json
import re
from datetime import datetime
from pathlib import Path

import polars as pl
from deltalake import DeltaTable
from normalize_stations import normalize_stations_response

PATTERN = re.compile(
    r"^stations_raw_(\d{8}_\d{6})\.json$"
)

STATIONS_SCHEMA = {
    "id": pl.String,
    "number": pl.String,
    "name": pl.String,
    "address": pl.String,
    "latitude": pl.Float64,
    "longitude": pl.Float64,
    "activate": pl.Int64,
    "dock_bikes": pl.Int64,
    "free_bases": pl.Int64,
    "geofenced_capacity": pl.Int64,
    "light": pl.Int64,
    "no_available": pl.Int64,
    "reservations_count": pl.Int64,
    "tipo_estacionPBSC": pl.String,
    "total_bases": pl.Int64,
    "virtualDelete": pl.Boolean,
    "lightNoOnTrip": pl.Int64,
    "overflow": pl.Boolean,
}


def get_collection_time(filename):
    match = PATTERN.fullmatch(filename)

    if not match:
        raise ValueError(f"Invalid filename: {filename}")

    return datetime.strptime(
        match.group(1), "%Y%m%d_%H%M%S"
    )


def already_imported(delta_path, filename):
    if not DeltaTable.is_deltatable(str(delta_path)):
        return False

    existing = (
        pl.scan_delta(str(delta_path))
        .filter(pl.col("source_file") == filename)
        .select("source_file")
        .limit(1)
        .collect()
    )

    return not existing.is_empty()



def import_snapshot(json_file, delta_path):
    if already_imported(delta_path, json_file.name):
        print(f"Already imported: {json_file.name}")
        return

    collected_at = get_collection_time(json_file.name)

    # Normalize the raw API response before constructing the Delta frame.
    payload = json.loads(json_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("Invalid stations response: expected a JSON object")
    stations = normalize_stations_response(payload)
    df = pl.DataFrame(stations, schema=STATIONS_SCHEMA, orient="row")

    if df.is_empty():
        print(f"Empty snapshot: {json_file.name}")
        return

    # Add collection metadata and partition column
    df = df.with_columns(
        pl.lit(collected_at)
        .cast(pl.Datetime("us"))
        .alias("collected_at"),

        pl.lit(collected_at.date())
        .cast(pl.Date)
        .alias("date"),

        pl.lit(json_file.name)
        .alias("source_file")
    )

    # Append to Delta Lake, partitioned by date
    df.write_delta(
        str(delta_path),
        mode="append",
        delta_write_options={
            "partition_by": ["date"],
            "schema_mode": "merge"
        }
    )

    print(
        f"Imported {df.height} stations "
        f"from {json_file.name} "
        f"(date={collected_at.date()})"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Normalize and import raw BiciMAD station snapshots into Delta Lake"
    )

    parser.add_argument(
        "input_path",
        type=Path,
        help="Input JSON file or directory"
    )

    parser.add_argument(
        "output_path",
        type=Path,
        help="Output Delta Lake table directory"
    )

    args = parser.parse_args()

    input_path = args.input_path.resolve()
    output_path = args.output_path.resolve()

    if input_path.is_file():
        if not PATTERN.fullmatch(input_path.name):
            parser.error("Invalid snapshot filename")

        files = [input_path]

    elif input_path.is_dir():
        files = sorted(
            file for file in input_path.glob(
                "stations_raw_*.json"
            )
            if PATTERN.fullmatch(file.name)
        )

    else:
        parser.error(
            f"Input path does not exist: {input_path}"
        )

    if not files:
        print("No matching JSON files found")
        return

    for json_file in files:
        import_snapshot(json_file, output_path)


if __name__ == "__main__":
    main()
