import pandas as pd
import re
import boto3
from io import StringIO
import json
import traceback

S3_BUCKET = "pocbotai"
S3_KEY    = "DBcheck.csv"

# — Cold start: load & normalize the CSV —
try:
    s3 = boto3.client('s3')
    obj = s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
    df  = pd.read_csv(StringIO(obj['Body'].read().decode('utf-8')))
    df["Data Point Name"] = df["Data Point Name"].str.strip().str.lower()
except Exception:
    df = pd.DataFrame()

RESPONSE_COLUMNS = ["P119","P143","P3021","P3089","P3368","P3019","P3090","P3373"]

def get_medication(name, selected_columns, display_mode):
    name = name.strip().lower()
    esc  = re.escape(name)
    matched = df[df["Data Point Name"].str.contains(esc, case=False, na=False, regex=True)]
    if matched.empty:
        return {"error": f"No records found for '{name}'"}

    if display_mode == "row-wise":
        rows = matched.replace({pd.NaT: None}).to_dict(orient="records")
        return {
            "response_type": "row_wise",
            "data": rows,
            "message": f"Found {len(rows)} row(s) for '{name}'"
        }

    cols = RESPONSE_COLUMNS if selected_columns.lower()=="all" else [
        c for c in selected_columns.split(",") if c.strip() in RESPONSE_COLUMNS
    ]
    out = []
    for _, r in matched.iterrows():
        avail = {c: r[c] for c in cols if pd.notna(r[c])}
        if avail:
            out.append({"data_point": r["Data Point Name"], "columns": avail})
    return {
        "response_type": "column_wise",
        "data": out,
        "message": f"Found {len(out)} column-wise result(s) for '{name}'"
    }

def lambda_handler(event, context):
    """
    Handles both OpenAPI‐schema action groups (requires apiPath/httpMethod echo)
    and function‐details action groups (requires responseState).
    """
    try:
        print("Event:", json.dumps(event, indent=2))
        # Extract parameters
        params = {p["name"]: p["value"] for p in event.get("parameters", [])}
        cond  = params.get("condition", "").strip()
        mode  = params.get("display_mode", "row-wise").strip().lower()
        cols  = params.get("selected_column", "all").strip()

        if not cond:
            raise ValueError("Missing required parameter: condition")

        result = get_medication(cond, cols, mode)
        if "error" in result:
            status, body = 404, {"error": result["error"]}
        else:
            status, body = 200, {
                "status": "success",
                "query": cond,
                "display_mode": mode,
                "selected_columns": cols,
                **result
            }

        # Build the response wrapper
        if "apiPath" in event and "httpMethod" in event:
            # API Schema mode: must echo apiPath & httpMethod exactly
            resp = {
                "messageVersion": "1.0",
                "response": {
                    "actionGroup":  event["actionGroup"],
                    "apiPath":      event["apiPath"],
                    "httpMethod":   event["httpMethod"],
                    "httpStatusCode": status,
                    "responseBody": {
                        "application/json": {"body": body}
                    }
                },
                "sessionAttributes":       event.get("sessionAttributes", {}),
                "promptSessionAttributes": event.get("promptSessionAttributes", {})
            }
        else:
            # Function-details mode: use responseState instead of apiPath/httpMethod
            resp = {
                "messageVersion": "1.0",
                "response": {
                    "actionGroup": event["actionGroup"],
                    "responseState": "SUCCESS" if status<400 else "FAILURE",
                    "responseBody": {
                        "application/json": {"body": body}
                    }
                },
                "sessionAttributes":       event.get("sessionAttributes", {}),
                "promptSessionAttributes": event.get("promptSessionAttributes", {})
            }

        return resp

    except Exception as e:
        print("Error:", traceback.format_exc())
        error_body = {"error": "Internal server error", "details": str(e)}
        # Mirror the same branching for errors
        if "apiPath" in event and "httpMethod" in event:
            action = {
                "actionGroup":    event["actionGroup"],
                "apiPath":        event["apiPath"],
                "httpMethod":     event["httpMethod"],
                "httpStatusCode": 500,
                "responseBody": {
                    "application/json": {"body": error_body}
                }
            }
        else:
            action = {
                "actionGroup":   event["actionGroup"],
                "responseState": "FAILURE",
                "responseBody": {
                    "application/json": {"body": error_body}
                }
            }
        return {
            "messageVersion": "1.0",
            "response":       action,
            "sessionAttributes":       event.get("sessionAttributes", {}),
            "promptSessionAttributes": event.get("promptSessionAttributes", {})
        }
