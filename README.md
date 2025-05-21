import os
import json
import boto3
import pandas as pd
import io
import re  # Added for punctuation handling

s3 = boto3.client('s3')

def lambda_handler(event, context):
    # Parse input parameters
    params = {p['name']: p.get('value') for p in event.get('parameters', [])}
    question = params.get('question', '').lower()
    plan_id = params.get('planID', '')  # Corrected parameter name to 'planID'

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

    # Normalize datapoint names for comparison
    df['normalized_names'] = df['datapointnames'].str.lower().str.replace('-', ' ').str.strip()

    # Normalize the question: remove punctuation, hyphens, and extra spaces
    normalized_question = re.sub(r'[^\w\s-]', '', question)  # Remove punctuation
    normalized_question = normalized_question.replace('-', ' ').strip().lower()
    question_words = normalized_question.split()

    best_match = None
    max_tokens = 0

    # Iterate through each row to find the best matching datapoint
    for _, row in df.iterrows():
        name_tokens = row['normalized_names'].split()
        # Check if all datapoint tokens are present in the question
        if all(token in question_words for token in name_tokens):
            # Prefer the entry with the most tokens (more specific match)
            if len(name_tokens) > max_tokens:
                max_tokens = len(name_tokens)
                best_match = row

    if best_match is None:
        return build_response("Sorry, I couldn't find that benefit in the data.", event)

    # Validate plan ID exists in CSV columns
    if plan_id not in df.columns:
        return build_response(f"Plan ID '{plan_id}' not found in data.", event)

    # Extract value and construct response
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
