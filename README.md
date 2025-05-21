import os
import json
import boto3
import csv

s3 = boto3.client('s3')

def lambda_handler(event, context):
    # 1) Parse input parameters from event
    # Bedrock can deliver parameters as a list of objects under event['parameters'].
    params = {p['name']: p.get('value') for p in event.get('parameters', [])}
    question = params.get('question', '').lower()  # user’s question text
    plan_id = params.get('planId', '')             # requested plan ID

    # 2) Load the CSV from S3
    bucket = os.environ.get('BUCKET_NAME')         # e.g. 'my-benefits-bucket'
    key = os.environ.get('CSV_KEY')               # e.g. 'benefits.csv'
    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
    except Exception as e:
        # Handle missing file or permissions
        answer = f"Error: unable to read data ({str(e)})"
    else:
        # Read CSV content
        content = resp['Body'].read().decode('utf-8').splitlines()
        reader = csv.DictReader(content)
        answer = None

        # 3) Find matching row by comparing 'datapointnames'
        for row in reader:
            name = row['datapointnames'].lower()
            # Simple matching: all words in name appear in question (order-insensitive)
            tokens = name.replace('-', ' ').split()
            if all(tok in question for tok in tokens):
                # Found the datapoint
                value = row.get(plan_id, None)
                if value:
                    answer = f"For plan {plan_id}, your **{row['datapointnames']}** is {value}."
                else:
                    answer = f"Plan {plan_id} not found in the data."
                break

        if answer is None:
            answer = "Sorry, I couldn't find that information in the plan data."

    # 4) Build the response in Bedrock’s expected format
    response_body = {
        'TEXT': {
            'body': answer
        }
    }
    function_response = {
        'actionGroup': event.get('actionGroup'),
        'function': event.get('function'),
        'functionResponse': {
            'responseBody': response_body
        }
    }
    # Preserve session attributes (if any)
    action_response = {
        'messageVersion': '1.0',
        'response': function_response,
        'sessionAttributes': event.get('sessionAttributes', {}),
        'promptSessionAttributes': event.get('promptSessionAttributes', {})
    }
    return action_response
