import pandas as pd
import re
import boto3
from io import StringIO
import json
import traceback

# Constants
S3_BUCKET = "pocbotai"
S3_KEY = "DBcheck.csv"

# Load CSV from S3
try:
    s3_client = boto3.client('s3')
    response = s3_client.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
    csv_data = response['Body'].read().decode('utf-8')
    df = pd.read_csv(StringIO(csv_data))
    df["Data Point Name"] = df["Data Point Name"].str.strip().str.lower()
except Exception as e:
    print("Error loading CSV from S3:", str(e))
    df = pd.DataFrame()

# Response columns
response_columns = ["P119", "P143", "P3021", "P3089", "P3368", "P3019", "P3090", "P3373"]

def get_medication(condition_name, selected_columns, display_mode):
    condition_name = condition_name.strip().lower()
    escaped_condition = re.escape(condition_name)
    filtered_df = df[df["Data Point Name"].str.contains(escaped_condition, case=False, na=False, regex=True)]

    if not filtered_df.empty:
        if display_mode == "row-wise":
            return {
                "response_type": "row_wise",
                "data": filtered_df.replace({pd.NaT: None}).to_dict(orient='records'),
                "message": f"Found {len(filtered_df)} row(s) for '{condition_name.capitalize()}'"
            }
        else:
            columns_to_check = response_columns if selected_columns.lower() == "all" else [
                col.strip() for col in selected_columns.split(',') if col.strip() in response_columns
            ]
            results = []
            for _, row in filtered_df.iterrows():
                result = {
                    "data_point": row['Data Point Name'],
                    "columns": {col: row[col] for col in columns_to_check if pd.notna(row[col])}
                }
                if result['columns']:
                    results.append(result)
            return {
                "response_type": "column_wise",
                "data": results,
                "message": f"Found {len(results)} column-wise result(s) for '{condition_name.capitalize()}'"
            }
    else:
        return {"error": f"No records found for '{condition_name}'"}

def lambda_handler(event, context):
    bedrock_response = {
        "actionGroup": event.get('actionGroup', ''),
        "apiPath": event.get('apiPath', ''),
        "httpMethod": event.get('httpMethod', ''),
        "httpStatusCode": 200,
        "responseBody": {
            "application/json": {
                "body": ""
            }
        }
    }

    try:
        print("Received event:", json.dumps(event, indent=2))

        # Extract parameters
        parameters = {p['name']: p['value'] for p in event.get('parameters', [])}
        condition_query = parameters.get('condition', '').strip()
        display_mode = parameters.get('display_mode', 'row-wise').strip().lower()
        selected_column = parameters.get('selected_column', 'all').strip()

        if not condition_query:
            bedrock_response['httpStatusCode'] = 400
            bedrock_response['responseBody']['application/json']['body'] = json.dumps({
                "error": "Missing required parameter: condition",
                "parameters_received": parameters
            })
            return bedrock_response

        # Get data from core logic
        result = get_medication(condition_query, selected_column, display_mode)
        
        # Handle error responses from core logic
        if 'error' in result:
            bedrock_response['httpStatusCode'] = 404
            bedrock_response['responseBody']['application/json']['body'] = json.dumps(result)
            return bedrock_response

        # Successful response
        bedrock_response['responseBody']['application/json']['body'] = json.dumps({
            "status": "success",
            "query": condition_query,
            "display_mode": display_mode,
            "selected_columns": selected_column,
            **result
        })

        return bedrock_response

    except Exception as e:
        print("Error:", traceback.format_exc())
        bedrock_response['httpStatusCode'] = 500
        bedrock_response['responseBody']['application/json']['body'] = json.dumps({
            "error": "Internal server error",
            "details": str(e),
            "stack_trace": traceback.format_exc()
        })
        return bedrock_response
