import shutil
import os
import logging
import time

import duckdb
import streamlit as st

from google.cloud import bigquery, storage
from google.oauth2 import service_account


logger = logging.getLogger(__name__)

# --- Constants ---
BUCKET_NAME     = "ebmdatalab"
GCS_DB_PATH     = "drug_tariff/tariffpricechanges-dev.duckdb"
GCS_PARQUET_DIR = "drug_tariff/tmp_parquet"
LOCAL_DB        = "/tmp/app.duckdb"
SQL_DIR         = os.path.join(os.path.dirname(os.path.abspath(__file__)), "queries")
REQUIRED_TABLES = {"prescribing", "tariff_price_changes", "vmpp_tariff_changes", "practices"}

TABLES_TO_BUILD = [
    ("prescribing",          "build_prescribing.sql"),
    ("tariff_price_changes", "build_tariff_price_changes.sql"),
    ("vmpp_tariff_changes",  "build_vmpp_tariff_changes.sql"),
    ("practices",            "build_practices.sql"),
]


# --- Auth / client helpers ---

def _credentials():
    return service_account.Credentials.from_service_account_info(st.secrets["gcp_service_account"])

def _gcs_client():
    return storage.Client(credentials=_credentials())

def _bq_client():
    return bigquery.Client(credentials=_credentials(), project="ebmdatalab")


# --- Helper functions ---

def _latest_bq_dates() -> dict:
    """Fetch latest prescribing and tariff dates from BigQuery in a single query."""
    bq = _bq_client()
    try:
        result = bq.query("""
            SELECT
                (SELECT DATE(MAX(month)) FROM `measures.global_data_lpzomnibus`) AS prescribing,
                (SELECT DATE(MAX(date))  FROM `dmd.tariffprice`)              AS tariff
        """).result()
        row = list(result)[0]
        return {
            "prescribing": str(row.prescribing) if row.prescribing else None,
            "tariff":      str(row.tariff)       if row.tariff      else None,
        }
    except Exception as e:
        st.error(f"Failed to fetch latest dates from BigQuery: {e}")
        return {"prescribing": None, "tariff": None}

def _cached_month_for_table(conn, table_name: str, date_col: str) -> str | None:
    try:
        result = conn.execute(
            f"SELECT MAX(CAST({date_col} AS DATE)) FROM {table_name}"
        ).fetchone()
        return str(result[0]) if result[0] else None
    except Exception:
        return None

def _is_db_current(conn, latest: dict) -> bool:
    """Return True if the local DuckDB has all required tables and is up to date."""
    tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
    return (
        REQUIRED_TABLES.issubset(tables)
        and _cached_month_for_table(conn, "prescribing", "month") == latest["prescribing"]
        and _cached_month_for_table(conn, "tariff_price_changes", "date") == latest["tariff"]
    )

def _delete_gcs_parquet(bucket, gcs_parquet_path: str):
    """Delete all blobs under a GCS prefix (parquet shards)."""
    try:
        blobs = list(bucket.list_blobs(prefix=gcs_parquet_path))
        for blob in blobs:
            blob.delete()
        logger.info(f"Deleted {len(blobs)} parquet shard(s) from GCS: {gcs_parquet_path}")
    except Exception as e:
        logger.warning(f"Failed to clean up parquet shards (non-fatal): {e}")

def _rebuild_table(conn, table_name: str, sql_file: str, bucket):
    """
    Export BQ query result directly to GCS as parquet (no Python RAM used),
    then load into DuckDB directly from GCS via httpfs.
    """
    with open(os.path.join(SQL_DIR, sql_file)) as f:
        sql = f.read()

    bq = _bq_client()
    gcs_parquet_path = f"{GCS_PARQUET_DIR}/{table_name}"
    gcs_uri = f"gs://{BUCKET_NAME}/{gcs_parquet_path}/*.parquet"

    # Step 1: run query into a temporary BQ table
    logger.info(f"Running BQ query for {table_name}...")
    tmp_table = f"ebmdatalab.tmp_exports.{table_name}_{int(time.time())}"

    job_config = bigquery.QueryJobConfig(
        destination=tmp_table,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
    )

    query_job = bq.query(sql, job_config=job_config)
    query_job.result()
    logger.info(f"BQ query complete for {table_name}")

    # Step 2: export the temp BQ table to GCS as parquet
    logger.info(f"Exporting {table_name} to GCS: {gcs_uri}")
    _delete_gcs_parquet(bucket, gcs_parquet_path)  # clean up any previous shards

    export_config = bigquery.ExtractJobConfig(
        destination_format=bigquery.DestinationFormat.PARQUET,
        compression=bigquery.Compression.SNAPPY,
    )
    extract_job = bq.extract_table(
        tmp_table,
        gcs_uri,
        job_config=export_config,
    )
    extract_job.result()
    logger.info(f"Export complete for {table_name}")

    # Step 3: delete the temp BQ table
    try:
        bq.delete_table(tmp_table)
        logger.info(f"Deleted temp BQ table: {tmp_table}")
    except Exception as e:
        logger.warning(f"Failed to delete temp BQ table {tmp_table} (non-fatal): {e}")

    # Step 4: load from GCS parquet directly into DuckDB via httpfs
    logger.info(f"Loading {table_name} into DuckDB from GCS parquet...")
    sa = dict(st.secrets["gcp_service_account"])
    private_key = sa["private_key"].replace("'", "''")  # escape any single quotes

    conn.execute("INSTALL httpfs; LOAD httpfs;")
    conn.execute(f"""
        CREATE OR REPLACE SECRET gcs_secret (
            TYPE GCS,
            KEY_ID '{sa["client_email"]}',
            SECRET '{private_key}',
            PROJECT '{sa["project_id"]}'
        )
    """)

    conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    conn.execute(f"""
        CREATE TABLE {table_name} AS
        SELECT * FROM read_parquet('{gcs_uri}')
    """)

    row_count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    logger.info(f"Loaded {row_count:,} rows into {table_name}")

    # Step 5: clean up GCS parquet shards
    _delete_gcs_parquet(bucket, gcs_parquet_path)

def _rebuild_all_tables(conn, bucket):
    for table_name, sql_file in TABLES_TO_BUILD:
        logger.info(f"Starting rebuild of {table_name}")
        _rebuild_table(conn, table_name, sql_file, bucket)

def _save_db_to_gcs(bucket):
    with st.spinner("Saving database to GCS for next time..."):
        tmp = LOCAL_DB + ".upload.tmp"
        shutil.copy2(LOCAL_DB, tmp)
        try:
            blob = bucket.blob(GCS_DB_PATH)
            blob.upload_from_filename(tmp, if_generation_match=None)
        except Exception as e:
            st.warning(f"Failed to save DB to GCS (non-fatal): {e}")
        finally:
            os.remove(tmp)


# --- Main entry point ---

@st.cache_resource
def get_duckdb_connection():
    storage_client = _gcs_client()
    bucket = storage_client.bucket(BUCKET_NAME)

    latest = _latest_bq_dates()

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
        _rebuild_all_tables(conn, bucket)
        conn.checkpoint()
        conn.close()

    _save_db_to_gcs(bucket)
    return duckdb.connect(LOCAL_DB)


@st.cache_resource
def get_latest_dates():
    conn = get_duckdb_connection()
    return {
        "prescribing": _cached_month_for_table(conn, "prescribing", "month"),
        "tariff":      _cached_month_for_table(conn, "tariff_price_changes", "date"),
    }
