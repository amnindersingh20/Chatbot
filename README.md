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
S3_KEY    = "2025 Medical SI HPCC for Chatbot Testing.csv"
FALLBACK_LAMBDA_NAME = "fallbackHandler"

# Initialize AWS clients
_s3     = boto3.client('s3')
_lambda = boto3.client('lambda')


def load_dataframe() -> pd.DataFrame:
    """
    - Pulls the CSV from S3
    - Strips and lower-cases the 'Data Point Name' column
    - Normalizes any en-dashes → hyphens and removes zero-width spaces
    - Strips all column names so plan columns can be looked up reliably
    """
    try:
        obj = _s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
        content = obj['Body'].read().decode('utf-8')
        df = pd.read_csv(StringIO(content))
        tog.info("CSV Columns Before Strip: %s", list(df.columns))

        # 1) Strip & normalize column names
        df.columns = (
            df.columns
              .astype(str)
              .str.strip()
        )

        # 2) Normalize your 'Data Point Name' column
        if 'Data Point Name' not in df.columns:
            raise KeyError("Missing 'Data Point Name' column in CSV")
        
        df['Data Point Name'] = (
            df['Data Point Name']
              .astype(str)
              .str.replace('–', '-', regex=False)     # en-dash → hyphen
              .str.replace('\u200b', '', regex=False)  # remove zero-width space
              .str.strip()
              .str.lower()
        )

        tog.info("CSV Columns After Strip: %s", list(df.columns))
        tog.info("First 20 Data Point Names (repr): %s",
                 [repr(x) for x in df['Data Point Name'].head(20)])
        return df

    except Exception as e:
        tog.error("Error loading CSV: %s", e, exc_info=True)
        return pd.DataFrame()


# Load once at cold start
df = load_dataframe()


def get_plan_value(name: str, plan_id: str) -> dict:
    """
    Returns the single cell under your plan column for a given data-point name.
    """
    name    = name.strip().lower()
    plan_id = str(plan_id).strip()

    # 1) Find matching row(s)
    esc     = re.escape(name)
    matched = df[
        df['Data Point Name']
          .str.contains(esc, case=False, na=False, regex=True)
    ]

    if matched.empty:
        return {
            'statusCode': 404,
            'message': f"No data-point '{name}' found",
            'error': True
        }

    # 2) Check plan column exists
    if plan_id not in df.columns:
        return {
            'statusCode': 404,
            'message': f"Plan '{plan_id}' not found",
            'error': True
        }

    # 3) Get first matching row and its plan-cell
    row   = matched.iloc[0]
    value = row.get(plan_id, None)
    if pd.isna(value):
        return {
            'statusCode': 404,
            'message': f"No value for '{name}' under plan '{plan_id}'",
            'error': True
        }

    return {
        'statusCode': 200,
        'message': f"Value for '{name}' under plan '{plan_id}'",
        'data': {
            'condition': name,
            'plan': plan_id,
            'value': value
        }
    }


def invoke_fallback(original_event: dict) -> dict:
    """
    If you still need to call your fallback Lambda on error.
    """
    try:
        resp = _lambda.invoke(
            FunctionName=FALLBACK_LAMBDA_NAME,
            InvocationType='RequestResponse',
            Payload=json.dumps(original_event).encode('utf-8')
        )
        payload = resp.get('Payload')
        raw = payload.read() if hasattr(payload, 'read') else payload

        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode('utf-8')
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {
                    'statusCode': HTTPStatus.INTERNAL_SERVER_ERROR,
                    'error': 'Fallback returned invalid JSON'
                }
        elif isinstance(raw, dict):
            return raw
        else:
            return {
                'statusCode': HTTPStatus.INTERNAL_SERVER_ERROR,
                'error': 'Fallback returned unexpected payload type'
            }

    except Exception as e:
        tog.error("Fallback invocation failed: %s", e, exc_info=True)
        return {
            'statusCode': HTTPStatus.INTERNAL_SERVER_ERROR,
            'error': f"Fallback handler error: {e}"
        }


def lambda_handler(event, context):
    tog.info("Received event: %s", json.dumps(event))

    # 1) Unwrap body/prompt/event but only json.loads() strings
    raw = event.get('body') or event.get('prompt') or event

    # decode bytes if needed
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode('utf-8')

    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
    elif isinstance(raw, dict):
        payload = raw
    else:
        payload = {}

    # 2) Normalize parameters list → dict
    params = payload.get('parameters') or {}
    if isinstance(params, list):
        params = {p.get('name'): p.get('value') for p in params if p.get('name')}

    condition = params.get('condition')
    plan      = params.get('plan')

    # 3) Validate inputs
    if not condition:
        return {
            'statusCode': HTTPStatus.BAD_REQUEST,
            'body': json.dumps({'error': "'condition' is required"})
        }
    if not plan:
        return {
            'statusCode': HTTPStatus.BAD_REQUEST,
            'body': json.dumps({'error': "'plan' is required"})
        }

    # 4) Perform lookup
    result = get_plan_value(condition, plan)
    status = result.get('statusCode', 500)
    if status != 200:
        # If you want to invoke fallback on lookup failures, uncomment:
        # fallback_event = event.copy()
        # fallback_params = [
        #     {'name': 'condition', 'value': condition},
        #     {'name': 'plan',      'value': plan}
        # ]
        # fallback_event['body']   = {'parameters': fallback_params}
        # fallback_event['prompt'] = {'parameters': fallback_params}
        # return invoke_fallback(fallback_event)

        return {
            'statusCode': status,
            'body': json.dumps({'error': result.get('message')})
        }

    # 5) Success — return the single-cell value
    return {
        'statusCode': 200,
        'body': json.dumps(result['data'])
    }
