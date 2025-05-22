import os
import json
import boto3
import pandas as pd
import io
import re
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client('s3')

def lambda_handler(event, context):
    try:
        # Log environment variables
        logger.info(f"BUCKET_NAME: {os.environ.get('BUCKET_NAME')}")
        logger.info(f"CSV_KEY: {os.environ.get('CSV_KEY')}")
        
        # Validate environment variables
        bucket = os.environ.get('BUCKET_NAME')
        key = os.environ.get('CSV_KEY')
        if not bucket or not key:
            return build_response("Configuration error: BUCKET_NAME or CSV_KEY is missing", event)
        
        # Verify S3 object exists
        logger.info(f"Checking S3://{bucket}/{key}")
        s3.head_object(Bucket=bucket, Key=key)
        
        # Get CSV content
        response = s3.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read()
        logger.info(f"Read {len(content)} bytes from S3")
        
        # Parse CSV
        df = pd.read_csv(io.BytesIO(content))
        logger.info("CSV parsed successfully")

        # Extract parameters
        params = {p['name']: p.get('value') for p in event.get('parameters', [])}
        question = params.get('question', '').lower()
        plan_id = params.get('planID', '')
        
        if not question or not plan_id:
            return build_response("Missing required parameters: question or planID", event)

        # Validate CSV structure
        if 'datapointnames' not in df.columns:
            return build_response("CSV missing 'datapointnames' column", event)
        
        if plan_id not in df.columns:
            return build_response(f"Plan ID {plan_id} not found in CSV", event)

        # Normalize data
        df['normalized_names'] = df['datapointnames'].str.lower().str.replace('-', ' ').str.strip()
        normalized_question = re.sub(r'[^\w\s-]', '', question).replace('-', ' ').strip().lower()
        question_words = normalized_question.split()

        # Find best match
        best_match = None
        max_tokens = 0
        
        for _, row in df.iterrows():
            name_tokens = row['normalized_names'].split()
            if all(token in question_words for token in name_tokens):
                if len(name_tokens) > max_tokens:
                    max_tokens = len(name_tokens)
                    best_match = row

        if not best_match:
            return build_response("No matching benefit found in data", event)

        # Get value and format response
        value = best_match[plan_id]
        datapoint = best_match['datapointnames']
        
        if pd.isna(value) or value == '':
            response_text = f"Value for '{datapoint}' not available for plan {plan_id}"
        else:
            response_text = f"For plan {plan_id}, your **{datapoint}** is {value}."

        return build_response(response_text, event)

    except s3.exceptions.NoSuchKey:
        logger.error("S3 object not found")
        return build_response("Data file not found in S3", event)
    except pd.errors.EmptyDataError:
        logger.error("Empty CSV file")
        return build_response("CSV file is empty or corrupted", event)
    except Exception as e:
        logger.error(f"Unhandled error: {str(e)}", exc_info=True)
        return build_response(f"Internal error: {str(e)}", event)

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
