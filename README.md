import pandas as pd
import re
import boto3
from io import StringIO
import json
import traceback

S3_BUCKET = "pocbotai"
S3_KEY = "DBcheck.csv"

# — Cold start: load and normalize your DataFrame once —
try:
    s3 = boto3.client('s3')
    obj = s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
    data = obj['Body'].read().decode('utf-8')
    df = pd.read_csv(StringIO(data))
    df["Data Point Name"] = df["Data Point Name"].str.strip().str.lower()
except Exception as e:
    print("Failed to load CSV:", str(e))
    df = pd.DataFrame()

RESPONSE_COLUMNS = ["P119","P143","P3021","P3089","P3368","P3019","P3090","P3373"]

def get_medication(name, selected_columns, display_mode):
    name = name.strip().lower()
    esc = re.escape(name)
    matched = df[df["Data Point Name"].str.contains(esc, case=False, na=False, regex=True)]

    if matched.empty:
        return {"error": f"No records found for '{name}'"}

    # Row-wise: return full rows
    if display_mode == "row-wise":
        records = matched.replace({pd.NaT: None}).to_dict(orient="records")
        return {
            "response_type": "row_wise",
            "data": records,
            "message": f"Found {len(records)} row(s) for '{name}'"
        }

    # Column-wise: filter to selected columns
    cols = RESPONSE_COLUMNS if selected_columns.lower() == "all" else [
        c for c in selected_columns.split(",") if c.strip() in RESPONSE_COLUMNS
    ]
    out = []
    for _, row in matched.iterrows():
        available = {c: row[c] for c in cols if pd.notna(row[c])}
        if available:
            out.append({
                "data_point": row["Data Point Name"],
                "columns": available
            })

    return {
        "response_type": "column_wise",
        "data": out,
        "message": f"Found {len(out)} column-wise result(s) for '{name}'"
    }

def lambda_handler(event, context):
    """
    Bedrock expects the Lambda response to be wrapped under a single "response" key.
    The "body" must be a JSON object, not a serialized string.
    """
    try:
        print("Event received:", json.dumps(event, indent=2))

        # Extract parameters passed by Bedrock
        params = {p["name"]: p["value"] for p in event.get("parameters", [])}
        cond = params.get("condition", "").strip()
        mode = params.get("display_mode", "row-wise").strip().lower()
        cols = params.get("selected_column", "all").strip()

        if not cond:
            # Missing required parameter
            raise ValueError("Missing required parameter: condition")

        # Perform lookup
        result = get_medication(cond, cols, mode)

        # Decide status and body based on lookup result
        if "error" in result:
            status_code = 404
            body = {"error": result["error"]}
        else:
            status_code = 200
            body = {
                "status": "success",
                "query": cond,
                "display_mode": mode,
                "selected_columns": cols,
                **result
            }

        # Build the Bedrock‐compliant response wrapper
        action_response = {
            "actionGroup":              event.get("actionGroup", ""),
            "apiPath":                  event.get("apiPath", ""),
            "httpMethod":               event.get("httpMethod", ""),
            "httpStatusCode":           status_code,
            "responseBody": {
                "application/json": {
                    "body": body
                }
            }
        }

        return {
            "messageVersion":          "1.0",
            "response":                action_response,
            "sessionAttributes":       event.get("sessionAttributes", {}),
            "promptSessionAttributes": event.get("promptSessionAttributes", {}),
        }

    except Exception as e:
        print("Handler error:", traceback.format_exc())
        error_body = {
            "error": "Internal server error",
            "details": str(e)
        }
        action_response = {
            "actionGroup":    event.get("actionGroup", ""),
            "apiPath":        event.get("apiPath", ""),
            "httpMethod":     event.get("httpMethod", ""),
            "httpStatusCode": 500,
            "responseBody": {
                "application/json": {
                    "body": error_body
                }
            }
        }
        return {
            "messageVersion":          "1.0",
            "response":                action_response,
            "sessionAttributes":       event.get("sessionAttributes", {}),
            "promptSessionAttributes": event.get("promptSessionAttributes", {}),
        }
