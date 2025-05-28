import logging
import json
import re
from io import StringIO
from http import HTTPStatus

import boto3
import pandas as pd

# Configure logging
log = logging.getLogger()
log.setLevel(logging.INFO)

# Config
S3_BUCKET = "pocbotai"
S3_KEY = "2025 Medical SI HPCC for Chatbot Testing.csv"
FALLBACK_LAMBDA_NAME = "fallbackHandler"

# Clients
_s3 = boto3.client('s3')
_lambda = boto3.client('lambda')

# Load DataFrame once at cold start
def load_dataframe():
    try:
        obj = _s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
        df = pd.read_csv(StringIO(obj['Body'].read().decode('utf-8')))
        df.columns = df.columns.astype(str).str.strip()
        if 'Data Point Name' not in df.columns:
            raise KeyError("Missing 'Data Point Name'")
        df['Data Point Name'] = (
            df['Data Point Name']
              .astype(str)
              .str.replace('–','-',regex=False)
              .str.replace('\u200b','',regex=False)
              .str.strip()
              .str.lower()
        )
        return df
    except Exception as e:
        log.exception("Failed to load CSV")
        return pd.DataFrame()

df = load_dataframe()


def get_plan_value(name: str, plan_id: str):
    name, plan_id = name.strip().lower(), str(plan_id).strip()
    if 'Data Point Name' not in df.columns:
        return {'statusCode': 500, 'message': 'CSV missing required column'}
    if plan_id not in df.columns:
        return {'statusCode': 404, 'message': f"Plan '{plan_id}' not found"}

    matched = df[df['Data Point Name'].str.contains(re.escape(name), case=False, na=False, regex=True)]
    if matched.empty:
        return {'statusCode': 404, 'message': f"No data-point '{name}' found"}

    val = matched.iloc[0].get(plan_id)
    if pd.isna(val):
        return {'statusCode': 404, 'message': f"No value for '{name}' under plan '{plan_id}'"}

    return {'statusCode': 200, 'data': {'condition': name, 'plan': plan_id, 'value': val}}


def invoke_fallback(event_payload: dict):
    try:
        response = _lambda.invoke(
            FunctionName=FALLBACK_LAMBDA_NAME,
            InvocationType='RequestResponse',
            Payload=json.dumps(event_payload).encode('utf-8')
        )
        result_bytes = response['Payload'].read()
        return json.loads(result_bytes)
    except Exception as e:
        log.exception("Fallback invocation failed")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': f"Fallback error: {str(e)}"})
        }


def lambda_handler(event, context):
    log.info("Received event: %s", json.dumps(event))

    try:
        # Step 1: Parse body
        raw = event.get('body') or event.get('prompt') or {}
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode('utf-8')
        if isinstance(raw, str):
            payload = json.loads(raw)
        elif isinstance(raw, dict):
            payload = raw
        else:
            payload = {}

        # Step 2: Parse parameters
        params = payload.get('parameters') or []
        if isinstance(params, dict):
            params = [{'name': k, 'value': v} for k, v in params.items()]
        param_dict = {p['name']: p['value'] for p in params if 'name' in p and 'value' in p}
        condition = param_dict.get('condition')
        plan = param_dict.get('plan')

        if not condition or not plan:
            missing = []
            if not condition: missing.append('condition')
            if not plan: missing.append('plan')
            return {'statusCode': 400, 'body': json.dumps({'error': f"Missing: {', '.join(missing)}"})}

        # Step 3: Query CSV
        result = get_plan_value(condition, plan)
        if result['statusCode'] != 200:
            log.warning("Primary lookup failed, invoking fallback.")
            fallback_event = {
                'body': json.dumps({'parameters': [
                    {'name': 'condition', 'value': condition},
                    {'name': 'plan', 'value': plan}
                ]})
            }
            return invoke_fallback(fallback_event)

        # Step 4: Success
        return {
            'statusCode': 200,
            'body': json.dumps(result['data'])
        }

    except Exception as e:
        log.exception("Unhandled error")
        fallback_event = {
            'body': json.dumps({'parameters': [
                {'name': 'condition', 'value': param_dict.get('condition', '')},
                {'name': 'plan', 'value': param_dict.get('plan', '')}
            ]})
        }
        return invoke_fallback(fallback_event)
