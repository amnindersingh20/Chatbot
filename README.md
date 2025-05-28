import logging
import json
import re
from io import StringIO
from http import HTTPStatus

import boto3
import pandas as pd

# Configure logging
tog = logging.getLogger()
tog.setLevel(logging.INFO)

# Configuration
S3_BUCKET = "pocbotai"
S3_KEY = "2025 Medical SI HPCC for Chatbot Testing.csv"
# Hardcoded fallback Lambda name
FALLBACK_LAMBDA_NAME = "fallbackHandler"

# Initialize AWS clients
_s3 = boto3.client('s3')
_lambda = boto3.client('lambda')


def load_dataframe() -> pd.DataFrame:
    try:
        obj = _s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
        content = obj['Body'].read().decode('utf-8')
        df = pd.read_csv(StringIO(content))
        tog.info("CSV Columns: %s", list(df.columns))
        
        if 'Data Point Name' not in df.columns:
            raise KeyError("Missing 'Data Point Name' column in CSV")

        df['Data Point Name'] = (
            df['Data Point Name']
              .astype(str)
              .str.strip()
              .str.lower()
        )
        df.columns = df.columns.str.strip()
        return df

    except Exception as e:
        tog.error("Error loading CSV: %s", e, exc_info=True)
        return pd.DataFrame()

# Load once at cold start
df = load_dataframe()


def get_medication(name: str) -> dict:
    """
    Retrieves matching records for a given medication/data-point name.
    Returns a dict with either 'data' on success, or 'error' on failure.
    """
    name = name.strip().lower()
    esc = re.escape(name)

    matched = df[df['Data Point Name'].str.contains(esc, case=False, na=False, regex=True)]
    if matched.empty:
        return {'statusCode': 404, 'message': f"No records found for '{name}'", 'error': True}

    # Convert to records
    rows = matched.where(pd.notna(matched), None).to_dict(orient='records')
    return {'statusCode': 200, 'message': f"Found {len(rows)} record(s)", 'data': rows}


def invoke_fallback(original_event: dict) -> dict:
    """
    Invokes the fallback lambda function and returns its response payload.
    """
    try:
        response = _lambda.invoke(
            FunctionName=FALLBACK_LAMBDA_NAME,
            InvocationType='RequestResponse',
            Payload=json.dumps(original_event).encode('utf-8')
        )
        payload = response.get('Payload')
        result_bytes = payload.read() if hasattr(payload, 'read') else payload
        return json.loads(result_bytes)
    except Exception as e:
        tog.error("Fallback invocation failed: %s", e, exc_info=True)
        return {'statusCode': 500, 'error': f"Fallback handler error: {e}"}


def lambda_handler(event, context):
    """
    Main entry point. Expects JSON payload with 'condition' parameter.
    If get_medication returns error or non-200 status, strip unwanted tokens and invoke fallback lambda.
    """
    tog.info("Received event: %s", json.dumps(event))

    try:
        body = event.get('body')
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except json.JSONDecodeError:
                pass

        params = (body or event).get('parameters') or {}
        # Allow both list or dict style
        if isinstance(params, list):
            params = {p.get('name'): p.get('value') for p in params}

        condition = params.get('condition')
        if not condition:
            return {'statusCode': HTTPStatus.BAD_REQUEST, 'body': json.dumps({'error': "'condition' is required"})}

        # Call primary handler
        result = get_medication(condition)
        status = result.get('statusCode', 500)
        msg = result.get('message', '')

        # Check for failure or apology
        if status != 200 or re.search(r"sorry|apology|no records", msg, re.IGNORECASE):
            tog.warning("Primary handler failed or apologized, preparing fallback...")
            # Strip unwanted tokens from user input
            stripped = re.sub(r"(column-wise|1651)", "", condition, flags=re.IGNORECASE).strip()
            # Build new event for fallback with stripped condition
            fallback_event = {**event}
            fallback_event['body'] = json.dumps({'parameters': [{'name': 'condition', 'value': stripped}]})
            return invoke_fallback(fallback_event)

        # Success: return data
        return {
            'statusCode': 200,
            'body': json.dumps({'message': msg, 'data': result.get('data', [])})
        }

    except Exception as e:
        tog.error("Unhandled exception: %s", e, exc_info=True)
        # On unexpected error, strip and invoke fallback
        stripped = re.sub(r"(column-wise|1651)", "", params.get('condition', ''), flags=re.IGNORECASE).strip()
        fallback_event = {**event}
        fallback_event['body'] = json.dumps({'parameters': [{'name': 'condition', 'value': stripped}]})
        return invoke_fallback(fallback_event)
