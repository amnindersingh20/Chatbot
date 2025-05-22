import pandas as pd
import re
import boto3
from io import StringIO
import json
import traceback

S3_BUCKET = "pocbotai"
S3_KEY    = "DBcheck.csv"

# Cold-start: load and normalize CSV
try:
    s3 = boto3.client('s3')
    obj = s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
    df  = pd.read_csv(StringIO(obj['Body'].read().decode('utf-8')))
    df["Data Point Name"] = df["Data Point Name"].str.strip().str.lower()
except Exception as e:
    print("CSV load failed:", str(e))
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

    cols = (
        RESPONSE_COLUMNS
        if selected_columns.lower() == "all"
        else [c for c in selected_columns.split(",") if c.strip() in RESPONSE_COLUMNS]
    )
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
    # **1) Dump the entire incoming event so you can inspect apiPath/httpMethod**
    print("=== FULL EVENT ===")
    print(json.dumps(event, indent=2))
    print("=== EVENT KEYS ===", list(event.keys()))

    try:
        # Extract parameters safely
        params = {p.get("name"): p.get("value") for p in event.get("parameters", [])}
        cond  = (params.get("condition")         or "").strip()
        mode  = (params.get("display_mode")      or "row-wise").strip().lower()
        cols  = (params.get("selected_column")   or "all").strip()

        if not cond:
            raise ValueError("Missing required parameter: condition")

        # Perform the lookup
        result = get_medication(cond, cols, mode)
        if "error" in result:
            status, body = 404, {"error": result["error"]}
        else:
            status, body = 200, {
                "status":           "success",
                "query":            cond,
                "display_mode":     mode,
                "selected_columns": cols,
                **result
            }

        # Pull incoming apiPath and httpMethod (if present)
        api_path    = event.get("apiPath")
        http_method = event.get("httpMethod")
        action_grp  = event.get("actionGroup", "")

        # Build the response wrapper
        if api_path and http_method:
            print(f"Echoing API schema mode → apiPath={api_path}, httpMethod={http_method}")
            response_wrapper = {
                "actionGroup":    action_grp,
                "apiPath":        api_path,     # must match exactly what you see in the logs!
                "httpMethod":     http_method,  # same here
                "httpStatusCode": status,
                "responseBody": {
                    "application/json": {"body": body}
                }
            }
        else:
            print("Function-details mode (no apiPath/httpMethod present)")
            response_wrapper = {
                "actionGroup":    action_grp,
                "responseState":  "SUCCESS" if status < 400 else "FAILURE",
                "responseBody": {
                    "application/json": {"body": body}
                }
            }

        return {
            "messageVersion":          "1.0",
            "response":                response_wrapper,
            "sessionAttributes":       event.get("sessionAttributes", {}),
            "promptSessionAttributes": event.get("promptSessionAttributes", {}),
        }

    except Exception as e:
        print("Handler error:", traceback.format_exc())
        err_body = {"error": "Internal server error", "details": str(e)}

        # Mirror the same branch so your error shape matches input style
        api_path    = event.get("apiPath")
        http_method = event.get("httpMethod")
        action_grp  = event.get("actionGroup", "")

        if api_path and http_method:
            error_wrapper = {
                "actionGroup":    action_grp,
                "apiPath":        api_path,
                "httpMethod":     http_method,
                "httpStatusCode": 500,
                "responseBody": {
                    "application/json": {"body": err_body}
                }
            }
        else:
            error_wrapper = {
                "actionGroup":    action_grp,
                "responseState":  "FAILURE",
                "responseBody": {
                    "application/json": {"body": err_body}
                }
            }

        return {
            "messageVersion":          "1.0",
            "response":                error_wrapper,
            "sessionAttributes":       event.get("sessionAttributes", {}),
            "promptSessionAttributes": event.get("promptSessionAttributes", {}),
        }
