import pandas as pd
import re
import boto3
from io import StringIO
import json
import traceback

S3_BUCKET = "pocbotai"
S3_KEY = "DBcheck.csv"

# Load the CSV once, at cold start
try:
    s3_client = boto3.client('s3')
    response = s3_client.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
    csv_data = response['Body'].read().decode('utf-8')
    df = pd.read_csv(StringIO(csv_data))
    df["Data Point Name"] = df["Data Point Name"].str.strip().str.lower()
except Exception as e:
    print("Error loading CSV from S3:", str(e))
    df = pd.DataFrame()

# Columns we can return
RESPONSE_COLUMNS = ["P119", "P143", "P3021", "P3089", "P3368", "P3019", "P3090", "P3373"]

def get_medication(condition_name: str, selected_columns: str, display_mode: str):
    condition = condition_name.strip().lower()
    escaped = re.escape(condition)
    matched = df[df["Data Point Name"].str.contains(escaped, case=False, na=False, regex=True)]

    if matched.empty:
        return {"error": f"No records found for '{condition_name}'"}

    # Row-wise dump of all columns
    if display_mode == "row-wise":
        records = matched.replace({pd.NaT: None}).to_dict(orient='records')
        return {
            "response_type": "row_wise",
            "data": records,
            "message": f"Found {len(records)} row(s) for '{condition_name.capitalize()}'"
        }

    # Column-wise: filter to selected columns
    cols = RESPONSE_COLUMNS if selected_columns.lower() == "all" else [
        c for c in selected_columns.split(",") if c.strip() in RESPONSE_COLUMNS
    ]
    results = []
    for _, row in matched.iterrows():
        available = {c: row[c] for c in cols if pd.notna(row[c])}
        if available:
            results.append({
                "data_point": row["Data Point Name"],
                "columns": available
            })

    return {
        "response_type": "column_wise",
        "data": results,
        "message": f"Found {len(results)} column-wise result(s) for '{condition_name.capitalize()}'"
    }

def lambda_handler(event, context):
    """
    Bedrock expects 'body' to be a JSON object, not a serialized string.
    We therefore assign a dict directly to responseBody['application/json']['body'].
    """
    base = {
        "messageVersion": "1.0",
        "actionGroup": event.get("actionGroup", ""),
        "httpStatusCode": 200,
        "responseBody": {
            "application/json": {
                "body": None  # fill in below
            }
        }
    }

    try:
        print("Received event:", json.dumps(event, indent=2))

        params = {p["name"]: p["value"] for p in event.get("parameters", [])}
        condition = params.get("condition", "").strip()
        display_mode = params.get("display_mode", "row-wise").strip().lower()
        selected_column = params.get("selected_column", "all").strip()

        if not condition:
            base["httpStatusCode"] = 400
            base["responseBody"]["application/json"]["body"] = {
                "error": "Missing required parameter: condition",
                "parameters_received": params
            }
            return base

        result = get_medication(condition, selected_column, display_mode)

        # Not found case
        if "error" in result:
            base["httpStatusCode"] = 404
            base["responseBody"]["application/json"]["body"] = {
                "error": result["error"]
            }
            return base

        # Success case: assign a dict directly, no json.dumps
        base["responseBody"]["application/json"]["body"] = {
            "status": "success",
            "query": condition,
            "display_mode": display_mode,
            "selected_columns": selected_column,
            **result
        }
        return base

    except Exception as e:
        print("Error processing request:", traceback.format_exc())
        base["httpStatusCode"] = 500
        base["responseBody"]["application/json"]["body"] = {
            "error": "Internal server error",
            "details": str(e),
            "stack_trace": traceback.format_exc()
        }
        return base
