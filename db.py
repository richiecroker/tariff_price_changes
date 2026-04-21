import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path

import duckdb
import streamlit as st

from google.cloud import bigquery, storage
from google.oauth2 import service_account


logger = logging.getLogger(__name__)

# --- Constants ---
BUCKET_NAME = "ebmdatalab"
GCS_DB_PATH = "drug_tariff/tariffpricechanges-dev.duckdb"
GCS_PARQUET_DIR = "drug_tariff/tmp_parquet"
LOCAL_DB = "/tmp/app.duckdb"
SQL_DIR = Path(__file__).resolve().parent / "queries"

REQUIRED_TABLES = {"prescribing", "tariff_price_changes", "vmpp_tariff_changes", "practices"}

TABLES_TO_BUILD = [
    ("prescribing", "build_prescribing.sql"),
    ("tariff_price_changes", "build_tariff_price_changes.sql"),
    ("vmpp_tariff_changes", "build_vmpp_tariff_changes.sql"),
    ("practices", "build_practices.sql"),
]

# Prevent two rebuilds from happening at once in the same process.
BUILD_LOCK = threading.Lock()


# --- Auth / client helpers ---

def _credentials():
    return service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"]
    )


def _gcs_client():
    return storage.Client(credentials=_credentials())


def _bq_client():
    return bigquery.Client(credentials=_credentials(), project="ebmdatalab")


# --- Helper functions ---

def _latest_bq_dates() -> dict:
    """Fetch latest prescribing and tariff dates from BigQuery in a single query."""
    bq = _bq_client()
    try:
        result = bq.query(
            """
            SELECT
                (SELECT DATE(MAX(month)) FROM `measures.global_data_lpzomnibus`) AS prescribing,
                (SELECT DATE(MAX(date))  FROM `dmd.tariffprice`)              AS tariff
            """
        ).result()
        row = list(result)[0]
        return {
            "prescribing": str(row.prescribing) if row.prescribing else None,
            "tariff": str(row.tariff) if row.tariff else None,
        }
    except Exception as e:
        st.error(f"Failed to fetch latest dates from BigQuery: {e}")
        return {"prescribing": None, "tariff": None}


def _save_metadata(conn, latest: dict):
    """Store the BQ dates in a small metadata table so we can check freshness next startup."""
    conn.execute("DROP TABLE IF EXISTS _metadata")
    conn.execute("CREATE TABLE _metadata (key VARCHAR, value VARCHAR)")
    conn.execute("INSERT INTO _metadata VALUES ('prescribing', ?)", [latest["prescribing"]])
    conn.execute("INSERT INTO _metadata VALUES ('tariff', ?)", [latest["tariff"]])
    logger.info("Saved metadata: %s", latest)


def _is_db_current(conn, latest: dict) -> bool:
    """Return True if the local DuckDB has all required tables and is up to date."""
    tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
    if not REQUIRED_TABLES.issubset(tables) or "_metadata" not in tables:
        return False

    rows = {r[0]: r[1] for r in conn.execute("SELECT key, value FROM _metadata").fetchall()}
    current = (
        rows.get("prescribing") == latest["prescribing"]
        and rows.get("tariff") == latest["tariff"]
    )
    logger.info("DB currency check — stored: %s, latest: %s, current: %s", rows, latest, current)
    return current


def _cached_metadata_value(conn, key: str) -> str | None:
    """Read a value from the metadata table."""
    try:
        result = conn.execute(
            "SELECT value FROM _metadata WHERE key = ?",
            [key],
        ).fetchone()
        return result[0] if result else None
    except Exception as e:
        logger.warning("Failed to get %s from metadata: %s", key, e)
        return None


def _delete_gcs_parquet(bucket, gcs_parquet_path: str):
    """Delete all blobs under a GCS prefix (parquet shards)."""
    try:
        blobs = list(bucket.list_blobs(prefix=gcs_parquet_path))
        for blob in blobs:
            blob.delete()
        logger.info("Deleted %d parquet shard(s) from GCS: %s", len(blobs), gcs_parquet_path)
    except Exception as e:
        logger.warning("Failed to clean up parquet shards (non-fatal): %s", e)


def _download_gcs_prefix(bucket, gcs_parquet_path: str, local_dir: str) -> list[str]:
    """Download all blobs under a GCS prefix into a local directory."""
    blobs = list(bucket.list_blobs(prefix=gcs_parquet_path))
    if not blobs:
        raise FileNotFoundError(
            f"No parquet shards found under gs://{BUCKET_NAME}/{gcs_parquet_path}/"
        )

    os.makedirs(local_dir, exist_ok=True)

    downloaded_files = []
    for blob in blobs:
        filename = os.path.basename(blob.name)
        local_path = os.path.join(local_dir, filename)
        blob.download_to_filename(local_path)
        downloaded_files.append(local_path)
        logger.info("  Downloaded %s", blob.name)

    return downloaded_files


def _rebuild_table(conn, table_name: str, sql_file: str, bucket):
    """
    Export BQ query result to GCS as parquet, download parquet shards to /tmp,
    load into DuckDB, then clean up.
    """
    sql_path = SQL_DIR / sql_file
    with open(sql_path) as f:
        sql = f.read()

    bq = _bq_client()

    # Unique paths for every rebuild to avoid collisions between sessions/reruns.
    run_id = uuid.uuid4().hex
    gcs_parquet_path = f"{GCS_PARQUET_DIR}/{table_name}/{run_id}"
    gcs_uri = f"gs://{BUCKET_NAME}/{gcs_parquet_path}/*.parquet"
    local_dir = tempfile.mkdtemp(prefix=f"{table_name}_{run_id}_")

    tmp_table = f"ebmdatalab.tmp_exports.{table_name}_{int(time.time())}_{run_id}"

    try:
        # Step 1: run query into a temporary BQ table
        logger.info("Running BQ query for %s...", table_name)
        job_config = bigquery.QueryJobConfig(
            destination=tmp_table,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
        )
        query_job = bq.query(sql, job_config=job_config)
        query_job.result()
        logger.info("BQ query complete for %s", table_name)

        # Step 2: export temp BQ table to GCS as parquet
        logger.info("Exporting %s to GCS: %s", table_name, gcs_uri)
        extract_job = bq.extract_table(
            tmp_table,
            gcs_uri,
            job_config=bigquery.ExtractJobConfig(
                destination_format=bigquery.DestinationFormat.PARQUET,
                compression=bigquery.Compression.SNAPPY,
            ),
        )
        extract_job.result()
        logger.info("Export to GCS complete for %s", table_name)

        # Step 3: download parquet shards from GCS to local tmp
        logger.info("Downloading parquet shards for %s...", table_name)
        _download_gcs_prefix(bucket, gcs_parquet_path, local_dir)
        logger.info("Downloaded parquet shards for %s", table_name)

        # Step 4: load into DuckDB from local parquet
        logger.info("Loading %s into DuckDB...", table_name)
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.execute(
            f"""
            CREATE TABLE {table_name} AS
            SELECT * FROM read_parquet('{local_dir}/*.parquet')
            """
        )

        row_count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        logger.info("Loaded %s rows into %s", f"{row_count:,}", table_name)

    finally:
        # Step 5: clean up local parquet shards
        shutil.rmtree(local_dir, ignore_errors=True)

        # Step 6: clean up GCS parquet shards
        _delete_gcs_parquet(bucket, gcs_parquet_path)

        # Step 7: delete the temp BQ table
        try:
            bq.delete_table(tmp_table, not_found_ok=True)
            logger.info("Deleted temp BQ table: %s", tmp_table)
        except Exception as e:
            logger.warning("Failed to delete temp BQ table %s (non-fatal): %s", tmp_table, e)


def _rebuild_all_tables(conn, bucket, latest: dict):
    for table_name, sql_file in TABLES_TO_BUILD:
        logger.info("Starting rebuild of %s", table_name)
        _rebuild_table(conn, table_name, sql_file, bucket)
    _save_metadata(conn, latest)


def _save_db_to_gcs(bucket):
    """Upload the local DuckDB file to GCS."""
    try:
        blob = bucket.blob(GCS_DB_PATH)
        blob.upload_from_filename(LOCAL_DB)
        logger.info("Saved DuckDB to GCS: gs://%s/%s", BUCKET_NAME, GCS_DB_PATH)
    except Exception as e:
        st.warning(f"Failed to save DB to GCS (non-fatal): {e}")


# --- Main entry point ---

@st.cache_resource
def get_duckdb_connection():
    storage_client = _gcs_client()
    bucket = storage_client.bucket(BUCKET_NAME)

    latest = _latest_bq_dates()

    with BUILD_LOCK:
        # --- Check 1: is there already a local DB that's up to date? ---
        if os.path.exists(LOCAL_DB):
            try:
                conn = duckdb.connect(LOCAL_DB)
                if _is_db_current(conn, latest):
                    logger.info("Local DuckDB is current, reusing.")
                    return conn
                conn.close()
            except Exception:
                pass

        # --- Check 2: download the cached DB from GCS and see if that's up to date ---
        tmp_path = LOCAL_DB + ".tmp"
        try:
            with st.spinner("Downloading cached database..."):
                bucket.blob(GCS_DB_PATH).download_to_filename(tmp_path)

            os.replace(tmp_path, LOCAL_DB)

            conn = duckdb.connect(LOCAL_DB)
            if _is_db_current(conn, latest):
                logger.info("GCS-cached DuckDB is current, reusing.")
                return conn

            conn.close()
            logger.info("GCS-cached DuckDB is stale or missing tables, doing full rebuild.")

        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        # --- Fallback: full rebuild from BigQuery via GCS parquet ---
        if os.path.exists(LOCAL_DB):
            os.remove(LOCAL_DB)

        with st.spinner("Rebuilding database from source data - this may take a few minutes..."):
            conn = duckdb.connect(LOCAL_DB)
            _rebuild_all_tables(conn, bucket, latest)
            conn.execute("FORCE CHECKPOINT")
            conn.close()

        _save_db_to_gcs(bucket)
        return duckdb.connect(LOCAL_DB)


@st.cache_resource
def get_latest_dates():
    conn = get_duckdb_connection()
    return {
        "prescribing": _cached_metadata_value(conn, "prescribing"),
        "tariff": _cached_metadata_value(conn, "tariff"),
    }
