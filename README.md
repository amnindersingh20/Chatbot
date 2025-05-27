
import logging
from typing import Dict, Any
from http import HTTPStatus
import json
import boto3
import pandas as pd
import re
from io import StringIO

logger = logging.getLogger()
logger.setLevel(logging.INFO)

S3_BUCKET = "pocbotai"
S3_KEY    = "2025 Medical SI HPCC for Chatbot Testing.csv"

def load_dataframe() -> pd.DataFrame:
    try:
        s3 = boto3.client('s3')
        obj = s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
        content = obj['Body'].read().decode('utf-8')
        df = pd.read_csv(StringIO(content))
        logger.info("CSV Columns: %s", list(df.columns))

        if 'Data Point Name' not in df.columns:
            raise KeyError("'Data Point Name' column is missing from the CSV")

        # Normalize the lookup column
        df['Data Point Name'] = (
            df['Data Point Name']
            .astype(str)
            .str.strip()
            .str.lower()
        )
        # Clean up other column names
        df.columns = df.columns.str.strip()

        return df
    except Exception as e:
        logger.error("Failed to load or parse CSV: %s", e, exc_info=True)
        return pd.DataFrame()

# Load dataframe at module import
df = load_dataframe()

def get_medication(
    name: str,
    selected_columns: str,
    display_mode: str
) -> Dict[str, Any]:
    name = name.strip().lower()
    esc = re.escape(name)
    matched = df[
        df['Data Point Name']
          .str.contains(esc, case=False, na=False, regex=True)
    ]

    if matched.empty:
        return {"error": f"No records found for '{name}'"}

    if display_mode == 'row-wise':
        rows = matched.where(pd.notna(matched), None).to_dict(orient='records')
        return {
            'response_type': 'row_wise',
            'data': rows,
            'message': f"Found {len(rows)} row(s) for '{name}'"
        }

    # Column-wise mode: user-specified columns
    sel_cols = [c.strip() for c in selected_columns.split(',')] if selected_columns else []
    # Exclude 'Data Point Name' and 'Option ID'
    valid_cols = [c for c in sel_cols if c in df.columns and c not in ('Data Point Name', 'Option ID')]

    if not valid_cols:
        available = [col for col in df.columns if col not in ('Data Point Name', 'Option ID')]
        return {
            'error': (
                f"No valid columns selected from input '{selected_columns}'. "
                f"Available columns: {available}"
            )
        }

    out = []
    for _, row in matched.iterrows():
        # Only include non-null values
        row_values = {c: row[c] for c in valid_cols if pd.notna(row[c])}
        if row_values:
            out.append({
                'data_point': row['Data Point Name'],
                'columns': row_values
            })

    return {
        'response_type': 'column_wise',
        'data': out,
        'message': f"Found {len(out)} column-wise result(s) for '{name}'"
    }


def lambda_handler(
    event: Dict[str, Any],
    context: Any
) -> Dict[str, Any]:
    logger.info("Raw event: %s", json.dumps(event))
    try:
        payload = event
        if 'body' in event and isinstance(event['body'], str):
            try:
                payload = json.loads(event['body'])
                logger.info("Unwrapped body to payload: %s", payload)
            except json.JSONDecodeError:
                logger.warning("Could not JSON-decode `body`; using top-level event")

        raw_params = payload.get('parameters', [])
        params = {p.get('name'): p.get('value') for p in raw_params}

        condition = params.get('condition', '').strip()
        sel       = params.get('selected_column', '').strip()

        # Auto-swap if necessary
        if re.fullmatch(r"P\d+", condition, re.IGNORECASE) and not re.fullmatch(r"P\d+", sel, re.IGNORECASE):
            logger.info("Auto-swapping: condition was '%s', selected_column was '%s'", condition, sel)
            condition, sel = sel, condition

        if not condition:
            raise ValueError("Missing required parameter: condition")

        result = get_medication(condition, sel, params.get('display_mode', 'column-wise').strip().lower())
        logger.info("Result from get_medication: %s", result)

        message = result.get('message', result.get('error', 'No message provided'))
        data = result.get('data', [])

        response_body = {
            'TEXT': {
                'body': f"{message}\n\n" + json.dumps(data, indent=2)
            }
        }

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

