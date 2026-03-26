import shutil
import logging
import os
import re

import duckdb
import pandas as pd
import streamlit as st

from google.cloud import bigquery, storage
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

BUCKET_NAME      = "ebmdatalab"
CSV_PREFIX       = "RC_tests/DRUG_TARIFF"
GCS_DB_PATH      = "drug_tariff/tariffpricechanges-dev.duckdb"
LOCAL_DB         = "/tmp/app.duckdb"
SQL_DIR          = os.path.join(os.path.dirname(os.path.abspath(__file__)), "queries")
#BQ_ODS_TABLE     = "ebmdatalab.scmd_pipeline.ods"


def _credentials():
    return service_account.Credentials.from_service_account_info(st.secrets["gcp_service_account"])

def _gcs_client():
    return storage.Client(credentials=_credentials())

def _bq_client():
    return bigquery.Client(credentials=_credentials(), project="ebmdatalab")
