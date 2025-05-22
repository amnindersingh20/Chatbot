import logging
from typing import Dict, Any
from http import HTTPStatus

import boto3
import pandas as pd
import re
from io import StringIO

# ——— Logger setup —————————————————————————————————————————————————————————————
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ——— S3 & CSV loading (done once at cold start) ————————————————————————————————
S3_BUCKET = "pocbotai"
S3_KEY    = "DBcheck.csv"

try:
    s3 = boto3.client('s3')
    obj = s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
    df  = pd.read_csv(StringIO(obj['Body'].read().decode('utf-8')))
    # Normalize the lookup key column
    df["Data Point Name"] = df["Data Point Name"].str.strip().str.lower()
    logger.info("Loaded CSV from S3: %s/%s", S3_BUCKET, S3_KEY)
except Exception as e:
    logger.error("Failed to load CSV from S3: %s", e)
    df = pd.DataFrame()

# ——— The columns you're willing to return in column-wise mode ————————————————————
RESPONSE_COLUMNS = [
    "P119", "P143", "P3021", "P3089",
    "P3368", "P3019", "P3090", "P3373"
]

def get_medication(name: str, selected_columns: str, display_mode: str) -> Dict[str, Any]:
    """
    Look up rows in the dataframe matching `name`, and return either row-wise
    or column-wise results based on `display_mode`.
    """
    name = name.strip().lower()
    esc  = re.escape(name)
    matched = df[df["Data Point Name"].str.contains(esc, case=False, na=False, regex=True)]

    if matched.empty:
        return {"error": f"No records found for '{name}'"}

    if display_mode == "row-wise":
        rows = matched.where(pd.notna(matched), None).to_dict(orient="records")
        return {
            "response_type": "row_wise",
            "data": rows,
            "message": f"Found {len(rows)} row(s) for '{name}'"
        }

    # — Column-wise mode —
    if selected_columns.lower() == "all":
        cols = RESPONSE_COLUMNS
    else:
        cols = [c.strip() for c in selected_columns.split(",")]
        cols = [c for c in cols if c in RESPONSE_COLUMNS]

    out = []
    for _, r in matched.iterrows():
        avail = {c: r[c] for c in cols if pd.notna(r[c])}
        if avail:
            out.append({
                "data_point": r["Data Point Name"],
                "columns":   avail
            })

    return {
        "response_type": "column_wise",
        "data": out,
        "message": f"Found {len(out)} column-wise result(s) for '{name}'"
    }

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda handler for processing Bedrock agent requests.
    Expects:
      - event['actionGroup']
      - event['function']
      - event['parameters']: list of { 'name': ..., 'value': ... }
    Returns the same actionGroup/function envelope with your lookup result.
    """
    try:
        action_group    = event['actionGroup']
        function_name   = event['function']
        message_version = event.get('messageVersion', 1)

        # Pull parameters into a dict for easy lookup
        params = { p['name']: p['value'] for p in event.get('parameters', []) }
        condition    = (params.get("condition")       or "").strip()
        display_mode = (params.get("display_mode")    or "row-wise").strip().lower()
        selected_col = (params.get("selected_column") or "all").strip()

        if not condition:
            raise ValueError("Missing required parameter: condition")

        # Run the lookup
        result = get_medication(condition, selected_col, display_mode)

        # Build your Bedrock-compatible response envelope
        action_response = {
            'actionGroup': action_group,
            'function':     function_name,
            'functionResponse': {
                'responseBody': result
            }
        }
        response = {
            'response':      action_response,
            'messageVersion': message_version
        }

        logger.info("Successful lookup for '%s': %s", condition, result)
        return response

    except KeyError as e:
        logger.error("Missing required field in event: %s", e)
        return {
            'statusCode': HTTPStatus.BAD_REQUEST,
            'body':       f"Error: Missing field {e}"
        }

    except Exception as e:
        logger.error("Unexpected error: %s", e, exc_info=True)
        return {
            'statusCode': HTTPStatus.INTERNAL_SERVER_ERROR,
            'body':       "Internal server error"
        }
