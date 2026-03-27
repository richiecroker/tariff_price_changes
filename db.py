import shutil
import os

import duckdb
import pandas as pd
import streamlit as st

from google.cloud import bigquery, storage
from google.oauth2 import service_account


# --- Constants ---
BUCKET_NAME     = "ebmdatalab"
GCS_DB_PATH     = "drug_tariff/tariffpricechanges-dev.duckdb"
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

def _latest_bq_month(table: str, date_col: str) -> str | None:
    bq = _bq_client()
    try:
        result = bq.query(f"SELECT DATE(MAX({date_col})) FROM `{table}`").result()
        row = list(result)[0]
        return str(row[0]) if row[0] else None
    except Exception as e:
        st.error(f"Failed to get latest {date_col} from {table}: {e}")
        return None

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

def _normalise_df(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if hasattr(df[col].dtype, "name") and "date" in str(df[col].dtype).lower():
            df[col] = pd.to_datetime(df[col]).dt.date
    return df

def _rebuild_table(conn, table_name: str, sql_file: str):
    with open(os.path.join(SQL_DIR, sql_file)) as f:
        sql = f.read()
    bq = _bq_client()
    df = _normalise_df(bq.query(sql).result().to_dataframe())
    conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    conn.register("_tmp", df)
    conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM _tmp")
    conn.unregister("_tmp")

def _rebuild_all_tables(conn):
    for table_name, sql_file in TABLES_TO_BUILD:
        _rebuild_table(conn, table_name, sql_file)

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
            return conn
        conn.close()
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    # --- Fallback: full rebuild from BigQuery ---
    if os.path.exists(LOCAL_DB):
        os.remove(LOCAL_DB)

    with st.spinner("Rebuilding database from source data - this may take a few minutes..."):
        conn = duckdb.connect(LOCAL_DB)
        _rebuild_all_tables(conn)
        conn.checkpoint()
        conn.close()

    _save_db_to_gcs(bucket)
    return duckdb.connect(LOCAL_DB)



@st.cache_resource
def get_latest_dates():
    conn = get_duckdb_connection()
    return {
        "prescribing": _latest_bq_month("measures.global_data_lpzomnibus", "month"),
        "tariff":      _cached_month_for_table(conn, "tariff_price_changes", "date"),
    }