import logging
from typing import Dict, Any
from http import HTTPStatus
import json
import boto3
import pandas as pd
import re
from io import StringIO

# ——— Logger setup —————————————————————————————————————————————————————————————
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ——— S3 & CSV loading (cold start) ——————————————————————————————————————————————
S3_BUCKET = "pocbotai"
S3_KEY    = "DBcheck.csv"

try:
    s3 = boto3.client('s3')
    obj = s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
    content = obj['Body'].read().decode('utf-8')
    df = pd.read_csv(StringIO(content))
    logger.info("CSV Columns: %s", list(df.columns))

    if 'Data Point Name' not in df.columns:
        raise KeyError("'Data Point Name' column is missing from the CSV")

    df["Data Point Name"] = (
        df["Data Point Name"]
        .astype(str)
        .str.strip()
        .str.lower()
    )
    logger.info("Successfully loaded and normalized 'Data Point Name' column")

except Exception as e:
    logger.error("Failed to load or parse CSV: %s", e, exc_info=True)
    df = pd.DataFrame()

# ——— Columns to return in column-wise mode ————————————————————————————————————————
RESPONSE_COLUMNS = [
    "P119", "P143", "P3021", "P3089",
    "P3368", "P3019", "P3090", "P3373"
]

def get_medication(name: str, selected_columns: str, display_mode: str) -> Dict[str, Any]:
    name = name.strip().lower()
    esc = re.escape(name)
    matched = df[df["Data Point Name"]
                 .str.contains(esc, case=False, na=False, regex=True)]

    if matched.empty:
        return {"error": f"No records found for '{name}'"}

    if display_mode == "row-wise":
        rows = matched.where(pd.notna(matched), None).to_dict(orient="records")
        return {
            "response_type": "row_wise",
            "data": rows,
            "message": f"Found {len(rows)} row(s) for '{name}'"
        }

    # Column-wise mode
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
    Handler with auto-detection & swap of condition vs. selected_column
    so that the UI order (P119/pre-natal) or the correct order
    (pre-natal/P119) both work.
    """
    try:
        # --- Unwrap API Gateway body if needed ---
        payload = event
        if 'body' in event and isinstance(event['body'], str):
            try:
                payload = json.loads(event['body'])
                logger.info("Unwrapped body to payload: %s", payload)
            except json.JSONDecodeError:
                logger.warning("Could not JSON-decode `body`; using top-level event")

        # --- Build params dict ---
        raw_params = payload.get('parameters', [])
        params = { p.get('name'): p.get('value') for p in raw_params }

        # --- Auto-detect & swap if needed ---
        cond = params.get('condition', '').strip()
        sel  = params.get('selected_column', '').strip()
        # If condition looks like P### (a column), but selected_column does not,
        # swap them.
        if re.fullmatch(r"P\d+", cond, re.IGNORECASE) and not re.fullmatch(r"P\d+", sel, re.IGNORECASE):
            logger.info("Auto-swapping: condition was '%s', selected_column was '%s'", cond, sel)
            cond, sel = sel, cond

        # --- Finalize variables with defaults ---
        condition       = cond
        selected_column = sel or "all"
        display_mode    = params.get('display_mode', 'column-wise').strip().lower()

        if not condition:
            raise ValueError("Missing required parameter: condition")

        # --- Invoke lookup ---
        result = get_medication(condition, selected_column, display_mode)
        logger.info("Result from get_medication: %s", result)

        # --- Build TEXT.body as plain string + indented JSON ---
        message = result.get('message', result.get('error', 'No message provided'))
        data    = result.get('data', [])

        response_body = {
            'TEXT': {
                'body': f"{message}\n\n" + json.dumps(data, indent=2)
            }
        }

        # --- Wrap into Bedrock Agent response format ---
        function_response = {
            'actionGroup':       payload.get('actionGroup'),
            'function':          payload.get('function'),
            'functionResponse': {
                'responseBody': response_body
            }
        }

        return {
            'messageVersion': payload.get('messageVersion', '1.0'),
            'response':       function_response
        }

    except KeyError as e:
        logger.error("Missing field in event/payload: %s", e, exc_info=True)
        return {
            'statusCode': HTTPStatus.BAD_REQUEST,
            'body':       json.dumps({'error': f"Missing field {e}"})
        }

    except Exception as e:
        logger.error("Unexpected error: %s", e, exc_info=True)
        return {
            'statusCode': HTTPStatus.INTERNAL_SERVER_ERROR,
            'body':       json.dumps({'error': str(e)})
        }
