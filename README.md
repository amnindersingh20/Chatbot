import pandas as pd
import re
import boto3
from io import StringIO
 
# Load data from S3
S3_BUCKET = "your-s3-bucket-name"
S3_Key = "DBcheck.csv"
 
s3_client = boto3.client('s3')
response = s3_client.get_object(Bucket=S3_BUCKET, Key=S3_Key)
csv_data = response['Body'].read().decode('utf-8')
 
# Read CSV into DataFrame
df = pd.read_csv(StringIO(csv_data))
df["Data Point Name"] = df["Data Point Name"].str.strip().str.lower()
 
# Define response columns
response_columns = ["P119", "P143", "P3021", "P3089", "P3368", "P3019", "P3090", "P3373"]
 
# Function to query information based on input parameters
def get_medication(condition_name, selected_columns, display_mode):
    condition_name = condition_name.strip().lower()  # Normalize input
    escaped_condition = re.escape(condition_name)  # Escape special characters
 
    # Filter DataFrame for the condition
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
 
# Event handler function
def event_handler(event):
    agent = event.get('agent', '')
    actionGroup = event.get('actionGroup', '')
    parameters = event.get('parameters', [])
 
    # Convert parameters into dictionary
    param_dict = {param['name']: param['value'] for param in parameters}
   
    # Extract relevant inputs
    condition_query = param_dict.get('condition', '').strip()
    display_mode = param_dict.get('display_mode', 'row-wise').strip().lower()
    selected_column = param_dict.get('selected_column', 'all').strip()
 
    if condition_query:
        response = get_medication(condition_query, selected_column, display_mode)
        return response
    else:
        return "No condition provided in parameters."
 
# Example usage:
if __name__ == "__main__":
    # Simulated event input
    event_data = {
        "agent": "chatbot_agent",
        "actionGroup": "med_query",
        "parameters": [
            {"name": "condition", "value": "diabetes"},
            {"name": "display_mode", "value": "column-wise"},
            {"name": "selected_column", "value": "P119"}
        ]
    }
 
    print(event_handler(event_data))
