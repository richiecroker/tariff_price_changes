import shutil
import logging
import os

import duckdb
import pandas as pd
import streamlit as st

from google.cloud import bigquery, storage
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

# --- Constants ---
BUCKET_NAME  = "ebmdatalab"
GCS_DB_PATH  = "drug_tariff/tariffpricechanges-dev.duckdb"
LOCAL_DB     = "/tmp/app.duckdb"
SQL_DIR      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "queries")


# --- Auth / client helpers ---

def _credentials():
    return service_account.Credentials.from_service_account_info(st.secrets["gcp_service_account"])

def _gcs_client():
    return storage.Client(credentials=_credentials())

def _bq_client():
    return bigquery.Client(credentials=_credentials(), project="ebmdatalab")


# --- Helper functions ---

def _latest_bq_month(table: str, date_col: str) -> str | None:
    bq = _bq_client()
    try:
        result = bq.query(f"SELECT DATE(MAX({date_col})) FROM `{table}`").result()
        row = list(result)[0]
        return str(row[0]) if row[0] else None
    except Exception as e:
        logger.error("Failed to get latest %s from %s: %s", date_col, table, e)
        return None

def _cached_month_for_table(conn, table_name: str, date_col: str) -> str | None:
    try:
        result = conn.execute(
            f"SELECT MAX(CAST({date_col} AS DATE)) FROM {table_name}"
        ).fetchone()
        return str(result[0]) if result[0] else None
    except Exception:
        return None

def _normalise_df(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if hasattr(df[col].dtype, "name") and "date" in str(df[col].dtype).lower():
            df[col] = pd.to_datetime(df[col]).dt.date
    return df

def _rebuild_table(conn, table_name: str, sql_file: str):
    with open(os.path.join(SQL_DIR, sql_file)) as f:
        sql = f.read()
    bq = _bq_client()
    try:
        df = _normalise_df(bq.query(sql).result().to_dataframe())
    except Exception as e:
        logger.error("BigQuery error rebuilding %s: %s", table_name, e)
        raise
    conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    conn.register("_tmp", df)
    conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM _tmp")
    conn.unregister("_tmp")

def _save_db_to_gcs(bucket):
    with st.spinner("Saving database to GCS for next time..."):
        tmp = LOCAL_DB + ".upload.tmp"
        shutil.copy2(LOCAL_DB, tmp)
        try:
            blob = bucket.blob(GCS_DB_PATH)
            blob.upload_from_filename(tmp, if_generation_match=None)
        except Exception as e:
            logger.warning("Failed to save DB to GCS (non-fatal): %s", e)
        finally:
            os.remove(tmp)


# --- Main entry point ---

@st.cache_resource
def get_duckdb_connection():
    storage_client = _gcs_client()
    bucket = storage_client.bucket(BUCKET_NAME)

    latest_prescribing_month = _latest_bq_month("hscic.normalised_prescribing", "month")
    latest_tariff_date = _latest_bq_month("dmd.tariffprice", "date")
    logger.info("Latest prescribing month in BQ: %s", latest_prescribing_month)
    logger.info("Latest tariff date in BQ: %s", latest_tariff_date)

    # --- Check 1: is there already a local DB that's up to date? ---
    if os.path.exists(LOCAL_DB):
        try:
            conn = duckdb.connect(LOCAL_DB)
            tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
            if (
                "prescribing" in tables
                and "tariff_price_changes" in tables
                and _cached_month_for_table(conn, "prescribing", "month") == latest_prescribing_month
                and _cached_month_for_table(conn, "tariff_price_changes", "date") == latest_tariff_date
            ):
                logger.info("Local DuckDB is up to date, reusing.")
                return conn
            conn.close()
            logger.info("Local DuckDB is stale.")
        except Exception as e:
            logger.warning("Local DuckDB unusable: %s", e)

    # --- Check 2: download the cached DB from GCS and see if that's up to date ---
    tmp_path = LOCAL_DB + ".tmp"
    try:
        with st.spinner("Downloading cached database..."):
            bucket.blob(GCS_DB_PATH).download_to_filename(tmp_path)
        os.replace(tmp_path, LOCAL_DB)
        conn = duckdb.connect(LOCAL_DB)
        tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
        if (
            "prescribing" in tables
            and "tariff_price_changes" in tables
            and _cached_month_for_table(conn, "prescribing", "month") == latest_prescribing_month
            and _cached_month_for_table(conn, "tariff_price_changes", "date") == latest_tariff_date
        ):
            logger.info("GCS-cached DuckDB is up to date, using it.")
            return conn
        logger.info("GCS-cached DuckDB is stale or missing tables, doing full rebuild.")
        conn.close()
    except Exception as e:
        logger.info("No usable GCS-cached DuckDB (%s), doing full rebuild.", e)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    # --- Fallback: full rebuild from BigQuery ---
    if os.path.exists(LOCAL_DB):
        os.remove(LOCAL_DB)

    with st.spinner("Rebuilding database from source data - this may take a few minutes..."):
        conn = duckdb.connect(LOCAL_DB)
        _rebuild_table(conn, "prescribing", "build_prescribing.sql")
        _rebuild_table(conn, "tariff_price_changes", "build_tariff_price_changes.sql")
        conn.checkpoint()
        conn.close()

    logger.info("DB file exists after rebuild: %s, size: %s",
                os.path.exists(LOCAL_DB),
                os.path.getsize(LOCAL_DB) if os.path.exists(LOCAL_DB) else "N/A")

    if not os.path.exists(LOCAL_DB):
        logger.error("DuckDB file not created at %s", LOCAL_DB)
        return duckdb.connect(LOCAL_DB)

    _save_db_to_gcs(bucket)
    return duckdb.connect(LOCAL_DB)