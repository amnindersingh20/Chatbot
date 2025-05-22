import pandas as pd
import re
import boto3
from io import StringIO
import json
import traceback

# Constants
S3_BUCKET = "pocbotai"
S3_KEY = "DBcheck.csv"

# Load CSV from S3 once (outside handler for performance)
try:
    s3_client = boto3.client('s3')
    response = s3_client.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
    csv_data = response['Body'].read().decode('utf-8')
    df = pd.read_csv(StringIO(csv_data))
    df["Data Point Name"] = df["Data Point Name"].str.strip().str.lower()
except Exception as e:
    print("Error loading CSV from S3:", str(e))
    df = pd.DataFrame()  # Fallback to empty DataFrame

# Define response columns
response_columns = ["P119", "P143", "P3021", "P3089", "P3368", "P3019", "P3090", "P3373"]

# Core logic
def get_medication(condition_name, selected_columns, display_mode):
    condition_name = condition_name.strip().lower()
    escaped_condition = re.escape(condition_name)
    filtered_df = df[df["Data Point Name"].str.contains(escaped_condition, case=False, na=False, regex=True)]

    if not filtered_df.empty:
        if display_mode == "row-wise":
            return f"Row-wise results for '{condition_name.capitalize()}':\n{filtered_df.to_string(index=False)}"
        else:
            responses = []
            columns_to_check = response_columns if selected_columns.lower() == "all" else [selected_columns] if selected_columns in response_columns else []
            for _, row in filtered_df.iterrows():
                row_responses = [f"{col}: {row[col]}" for col in columns_to_check if col in filtered_df.columns and pd.notna(row[col])]
                if row_responses:
                    responses.append(f"Data Point Name: {row['Data Point Name']} | " + " | ".join(row_responses))
            return f"Plan Column-wise responses for '{condition_name.capitalize()}':\n" + "\n".join(responses) if responses else f"No matching records found in '{selected_columns}' for '{condition_name}'."
    else:
        return f"No record found for '{condition_name}'."

# Lambda handler
def lambda_handler(event, context):
    try:
        print("Received event:", json.dumps(event))  # Log the incoming event

        parameters = event.get('parameters', [])
        param_dict = {param['name']: param['value'] for param in parameters}
        condition_query = param_dict.get('condition', '').strip()
        display_mode = param_dict.get('display_mode', 'row-wise').strip().lower()
        selected_column = param_dict.get('selected_column', 'all').strip()

        if condition_query:
            response = get_medication(condition_query, selected_column, display_mode)
            print("Response:", response)
            return {
                "message": response
            }
        else:
            return {
                "message": "No condition provided in parameters."
            }

    except Exception as e:
        print("Error occurred:", str(e))
        traceback.print_exc()
        return {
            "message": "An error occurred while processing your request."
        }
