Response body: {'TEXT': {'body': '{"message": "Found 3 column-wise result(s) for \'pre-natal\'", "data": [{"data_point": "pre-natal doctor visits - maternity", "columns": {"P119": "10"}}, {"data_point": "family planning, pre-natal & in-hospital delivery services-network", "columns": {"P119": "10% Coinsurance after Annual Deductible"}}, {"data_point": "family planning, pre-natal & in-hospital delivery services-non-network", "columns": {"P119": "50% Coinsurance after Annual Deductible"}}]}'}}



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
S3_KEY    = "DBcheck.csv"

try:
    s3 = boto3.client('s3')
    obj = s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
    df = pd.read_csv(StringIO(obj['Body'].read().decode('utf-8')))

    # Log the columns we actually loaded
    logger.info("CSV Columns: %s", list(df.columns))

    # Ensure the key column exists
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

    param_dict = {p['name']: p['value'] for p in event['parameters']}
    result = get_medication(
        param_dict['condition'],
        param_dict['selected_column'],
        param_dict['display_mode']
    )

    actionGroup = event['actionGroup']
    function = event['function']
    parameters = event.get('parameters', [])

    response_body = {
        'TEXT': {
            'body': json.dumps({
                'message': result['message'],
                'data': result['data']
            })
        }
    }
    
    function_response = {
        'actionGroup': event['actionGroup'],
        'function': event['function'],
        'functionResponse': {
            'responseBody': response_body
        }
    }
    
    # session_attributes = event['sessionAttributes']
    # prompt_session_attributes = event['promptSessionAttributes']
    
    action_response = {
        'messageVersion': '1.0', 
        'response': function_response
        # 'sessionAttributes': session_attributes,
        # 'promptSessionAttributes': prompt_session_attributes
    }
        
    return action_response
