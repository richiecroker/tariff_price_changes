import shutil       
import logging      
import os           
import re           # for regex pattern matching ???????

import duckdb      
import pandas as pd
import streamlit as st

from google.cloud import bigquery, storage  
from google.oauth2 import service_account   

# creates a logger named after this module e.g. "data_loader"
logger = logging.getLogger(__name__)

# --- Constants ---
BUCKET_NAME  = "ebmdatalab"                          # GCS bucket where files live
GCS_DB_PATH  = "drug_tariff/tariffpricechanges-dev.duckdb"  # where the cached DB lives in GCS
LOCAL_DB     = "/tmp/app.duckdb"                     # where the DB is stored locally on the server
SQL_DIR      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "queries")  # path to the /queries folder next to this file
BQ_ODS_TABLE = "ebmdatalab.scmd_pipeline.ods"        # BigQuery table for ODS data


# --- Auth / client helpers ---

def _credentials():
    return service_account.Credentials.from_service_account_info(st.secrets["gcp_service_account"])

def _gcs_client():
    return storage.Client(credentials=_credentials())

def _bq_client():
    return bigquery.Client(credentials=_credentials(), project="ebmdatalab")


# --- Helper functions ---

def _latest_bq_month() -> str | None:
    bq = _bq_client()
    try:
        result = bq.query("SELECT max(month) FROM `ebmdatalab.measures.global_data_lpzomnibus`").result()
        row = list(result)[0]
        return str(row[0])  # returns as yyyy-mm-dd string
    except Exception as e:
        logger.error("Failed to get latest month from BigQuery: %s", e)
        return None

def _cached_month(conn) -> str | None:
    try:
        result = conn.execute(
            "SELECT MAX(CAST(month AS DATE)) FROM prescribing"
        ).fetchone()
        return str(result[0]) if result[0] else None
    except Exception:
        return None

def _normalise_df(df: pd.DataFrame) -> pd.DataFrame:
    # BigQuery returns date columns in a format DuckDB doesn't like
    # this converts any date/datetime columns to plain Python date objects
    for col in df.columns:
        if hasattr(df[col].dtype, "name") and "date" in str(df[col].dtype).lower():
            df[col] = pd.to_datetime(df[col]).dt.date
    return df

def _rebuild_table(conn, table_name: str, sql_file: str):
    # reads a SQL file, runs it in BigQuery, and loads the result into DuckDB
    with open(os.path.join(SQL_DIR, sql_file)) as f:
        sql = f.read()
    bq = _bq_client()
    try:
        df = _normalise_df(bq.query(sql).result().to_dataframe())
    except Exception as e:
        logger.error("BigQuery error rebuilding %s: %s", table_name, e)
        raise  # re-raises the exception so the app knows something went wrong
    conn.execute(f"DROP TABLE IF EXISTS {table_name}")  # remove old version if it exists
    conn.register("_tmp", df)                           # temporarily expose the dataframe to DuckDB
    conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM _tmp")  # write it as a proper table
    conn.unregister("_tmp")                             # clean up the temporary reference

def _save_db_to_gcs(bucket):
    # saves the local DuckDB file up to GCS so it can be reused next time the app starts
    with st.spinner("Saving database to GCS for next time..."):
        tmp = LOCAL_DB + ".upload.tmp"
        shutil.copy2(LOCAL_DB, tmp)  # copy to a temp file first (avoids uploading a file that's being written)
        try:
            blob = bucket.blob(GCS_DB_PATH)
            blob.upload_from_filename(tmp, if_generation_match=None)
        except Exception as e:
            logger.warning("Failed to save DB to GCS (non-fatal): %s", e)  # not fatal, app can still run
        finally:
            os.remove(tmp)  # always clean up the temp file


# --- Main entry point ---

@st.cache_resource  # tells Streamlit to only run this once and reuse the connection across sessions
def get_duckdb_connection():
    storage_client = _gcs_client()
    bucket = storage_client.bucket(BUCKET_NAME)

    # find out what the latest available data month is
    latest_csv = _latest_csv_yyyymm(bucket)
    logger.info("Latest CSV month in GCS: %s", latest_csv)

    # --- Check 1: is there already a local DB that's up to date? ---
    if os.path.exists(LOCAL_DB):
        try:
            conn = duckdb.connect(LOCAL_DB)
            tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
            if _cached_yyyymm(conn) == latest_csv and "ods_mapping" in tables and "prescribing" in tables:
                logger.info("Local DuckDB is up to date, reusing.")
                return conn  # already have what we need, return early
            conn.close()
            logger.info("Local DuckDB is stale.")
        except Exception as e:
            logger.warning("Local DuckDB unusable: %s", e)

    # --- Check 2: download the cached DB from GCS and see if that's up to date ---
    tmp_path = LOCAL_DB + ".tmp"
    try:
        with st.spinner("Downloading cached database..."):
            bucket.blob(GCS_DB_PATH).download_to_filename(tmp_path)
        os.replace(tmp_path, LOCAL_DB)  # atomically replace local DB with downloaded version
        conn = duckdb.connect(LOCAL_DB)
        tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
        if _cached_yyyymm(conn) == latest_csv and "ods_mapping" in tables and "prescribing" in tables:
            logger.info("GCS-cached DuckDB is up to date, using it.")
            return conn  # GCS cache is fresh enough, use it
        logger.info("GCS-cached DuckDB is stale or missing tables, doing full rebuild.")
        conn.close()
    except Exception as e:
        logger.info("No usable GCS-cached DuckDB (%s), doing full rebuild.", e)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    # --- Fallback: full rebuild from BigQuery ---
    if os.path.exists(LOCAL_DB):
        os.remove(LOCAL_DB)  # start fresh

    with st.spinner("Rebuilding database from source data - this may take a few minutes..."):
        conn = duckdb.connect(LOCAL_DB)
        _rebuild_table(conn, "prescribing", "build_prescribing.sql")   # pull prescribing data from BQ
        _rebuild_table(conn, "ods_mapping", "build_ods_mapping.sql")   # pull ODS mapping from BQ
        conn.checkpoint()  # flush everything to disk
        conn.close()

    logger.info("DB file exists after rebuild: %s, size: %s",
                os.path.exists(LOCAL_DB),
                os.path.getsize(LOCAL_DB) if os.path.exists(LOCAL_DB) else "N/A")

    # sanity check — if the file still doesn't exist something went badly wrong
    if not os.path.exists(LOCAL_DB):
        logger.error("DuckDB file not created at %s", LOCAL_DB)
        return duckdb.connect(LOCAL_DB)

    # save the freshly built DB to GCS for next time
    _save_db_to_gcs(bucket)
    return duckdb.connect(LOCAL_DB)
