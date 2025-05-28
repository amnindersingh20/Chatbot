import logging
import json
import re
from io import StringIO
from http import HTTPStatus

import boto3
import pandas as pd

# ---------- same setup as before ----------
tog = logging.getLogger()
tog.setLevel(logging.INFO)

S3_BUCKET           = "pocbotai"
S3_KEY              = "2025 Medical SI HPCC for Chatbot Testing.csv"
FALLBACK_LAMBDA_NAME = "fallbackHandler"

_s3     = boto3.client('s3')
_lambda = boto3.client('lambda')


def load_dataframe() -> pd.DataFrame:
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
    except Exception:
        tog.exception("Failed to load CSV")
        return pd.DataFrame()

df = load_dataframe()


def get_plan_value(name: str, plan_id: str) -> dict:
    name, plan_id = name.strip().lower(), str(plan_id).strip()
    esc = re.escape(name)
    matched = df[df['Data Point Name'].str.contains(esc, case=False, na=False, regex=True)]
    if matched.empty:
        return {'statusCode': 404, 'message': f"No data-point '{name}'"}
    if plan_id not in df.columns:
        return {'statusCode': 404, 'message': f"Plan '{plan_id}' not found"}
    val = matched.iloc[0].get(plan_id)
    if pd.isna(val):
        return {'statusCode':404, 'message':f"No value for '{name}' under plan '{plan_id}'"}
    return {'statusCode':200, 'data':{'condition':name,'plan':plan_id,'value':val}}


def lambda_handler(event, context):
    tog.info("Event: %s", event)

    # --- 1) extract payload dict from event['body'] (string or dict)
    raw = event.get('body')
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

    # --- 2) pull params
    params = payload.get('parameters') or []
    if isinstance(params, dict):
        # in case someone passed {name:value} style
        params = [{'name':k,'value':v} for k,v in params.items()]
    if isinstance(params, list):
        params = {p['name']: p['value'] for p in params if 'name' in p and 'value' in p}

    condition = params.get('condition')
    plan      = params.get('plan')

    # --- 3) validate
    if not condition:
        return {'statusCode':400, 'body': json.dumps({'error': "'condition' required"})}
    if not plan:
        return {'statusCode':400, 'body': json.dumps({'error': "'plan' required"})}

    # --- 4) lookup
    result = get_plan_value(condition, plan)
    if result['statusCode'] != 200:
        return {'statusCode': result['statusCode'],
                'body': json.dumps({'error': result.get('message')})}

    # --- 5) success
    return {'statusCode':200, 'body': json.dumps(result['data'])}
