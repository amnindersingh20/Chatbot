import os
import json
import boto3
import pandas as pd
import io

s3 = boto3.client('s3')

def lambda_handler(event, context):
    # Parse input parameters
    params = {p['name']: p.get('value') for p in event.get('parameters', [])}
    question = params.get('question', '').lower()
    plan_id = params.get('planId', '')

    # S3 bucket and key from environment
    bucket = os.environ.get('BUCKET_NAME')
    key = os.environ.get('CSV_KEY')

    try:
        # Get the CSV file from S3
        response = s3.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read()
        
        # Read CSV with pandas
        df = pd.read_csv(io.BytesIO(content))
    except Exception as e:
        return build_response(f"Error reading data: {str(e)}", event)

    if 'datapointnames' not in df.columns:
        return build_response("The CSV is missing a 'datapointnames' column.", event)

    # Normalize for comparison
    df['normalized_names'] = df['datapointnames'].str.lower().str.replace('-', ' ').str.strip()

    # Clean question similarly
    normalized_question = question.replace('-', ' ').strip()

    # Simple match: check if all words in a row's name are in the question
    best_match = None
    for _, row in df.iterrows():
        name_tokens = row['normalized_names'].split()
        if all(tok in normalized_question for tok in name_tokens):
            best_match = row
            break

    if best_match is None:
        return build_response("Sorry, I couldn't find that benefit in the data.", event)

    # Extract value for plan ID
    if plan_id not in df.columns:
        return build_response(f"Plan ID '{plan_id}' not found in data.", event)

    value = best_match[plan_id]
    datapoint = best_match['datapointnames']
    if pd.isna(value) or value == '':
        answer = f"The value for '{datapoint}' is not available for plan {plan_id}."
    else:
        answer = f"For plan {plan_id}, your **{datapoint}** is {value}."

    return build_response(answer, event)

def build_response(answer_text, event):
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup"),
            "function": event.get("function"),
            "functionResponse": {
                "responseBody": {
                    "TEXT": {
                        "body": answer_text
                    }
                }
            }
        },
        "sessionAttributes": event.get("sessionAttributes", {}),
        "promptSessionAttributes": event.get("promptSessionAttributes", {})
    }
