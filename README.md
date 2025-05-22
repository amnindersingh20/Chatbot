import pandas as pd
import re
import boto3
from io import StringIO
import json
import traceback

S3_BUCKET = "pocbotai"
S3_KEY    = "DBcheck.csv"

# — Cold start: load & normalize your CSV once —
try:
    s3 = boto3.client('s3')
    obj = s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
    df  = pd.read_csv(StringIO(obj['Body'].read().decode('utf-8')))
    df["Data Point Name"] = df["Data Point Name"].str.strip().str.lower()
except Exception as e:
    print("Failed to load CSV:", str(e))
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

    # Column-wise
    cols = RESPONSE_COLUMNS if selected_columns.lower() == "all" else [
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
    Function-details mode:
    Must return:
      {
        "messageVersion": "1.0",
        "response": {
          "actionGroup":   "...",
          "function":      "...",
          "functionResponse": {
            "responseState": "SUCCESS|FAILURE|REPROMPT",
            "responseBody": {
              "TEXT": { "body": "JSON-formatted string" }
            }
          }
        },
        "sessionAttributes": { … },
        "promptSessionAttributes": { … }
      }
    """
    try:
        print("Event keys:", list(event.keys()))

        # Extract parameters
        params = {p.get("name"): p.get("value") for p in event.get("parameters", [])}
        cond  = (params.get("condition")         or "").strip()
        mode  = (params.get("display_mode")      or "row-wise").strip().lower()
        cols  = (params.get("selected_column")   or "all").strip()

        if not cond:
            raise ValueError("Missing required parameter: condition")

        result = get_medication(cond, cols, mode)
        if "error" in result:
            status = "FAILURE"
            payload = {"error": result["error"]}
        else:
            status = "SUCCESS"
            payload = {
                "status":           "success",
                "query":            cond,
                "display_mode":     mode,
                "selected_columns": cols,
                **result
            }

        # Build the function-details response
        func_name = event.get("function", "")
        function_response = {
            "actionGroup":      event.get("actionGroup", ""),
            "function":         func_name,
            "functionResponse": {
                "responseState": status,
                "responseBody": {
                    # TEXT is the only supported content type for function-details
                    "TEXT": {
                        # Body must be a JSON-formatted string
                        "body": json.dumps(payload)
                    }
                }
            }
        }

        return {
            "messageVersion":          "1.0",
            "response":                function_response,
            "sessionAttributes":       event.get("sessionAttributes", {}),
            "promptSessionAttributes": event.get("promptSessionAttributes", {}),
        }

    except Exception as e:
        print("Handler error:", traceback.format_exc())
        err_payload = {"error": "Internal server error", "details": str(e)}

        # Error must follow the same function-details shape
        func_name = event.get("function", "")
        function_response = {
            "actionGroup":      event.get("actionGroup", ""),
            "function":         func_name,
            "functionResponse": {
                "responseState": "FAILURE",
                "responseBody": {
                    "TEXT": {
                        "body": json.dumps(err_payload)
                    }
                }
            }
        }

        return {
            "messageVersion":          "1.0",
            "response":                function_response,
            "sessionAttributes":       event.get("sessionAttributes", {}),
            "promptSessionAttributes": event.get("promptSessionAttributes", {}),
        }
