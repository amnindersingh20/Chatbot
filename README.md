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

# Load and cache CSV in global scope for Lambda cold start
_df_cache = None

def _load_dataframe():
    global _df_cache
    if _df_cache is None:
        bucket = os.environ.get('BUCKET_NAME')
        key = os.environ.get('CSV_KEY')
        if not bucket or not key:
            raise RuntimeError("Configuration error: BUCKET_NAME or CSV_KEY is missing")
        # fetch from S3
        resp = s3.get_object(Bucket=bucket, Key=key)
        raw = resp['Body'].read()
        df = pd.read_csv(io.BytesIO(raw))
        # normalize the "Data Point Name" column
        df['datapointnames'] = df['Data Point Name'].fillna('')
        df['normalized_names'] = (
            df['datapointnames']
              .str.strip()
              .str.lower()
              .str.replace('-', ' ')
        )
        _df_cache = df
    return _df_cache


def lambda_handler(event, context):
    try:
        logger.info(f"Event received: {json.dumps(event)}")

        # load dataframe
        df = _load_dataframe()

        # extract params
        params = {p['name']: p.get('value') for p in event.get('parameters', [])}
        condition = params.get('condition', '').strip().lower()
        display_mode = params.get('display_mode', 'row-wise').strip().lower()
        selected_column = params.get('selected_column', 'all').strip()

        if not condition:
            return build_response("Missing required parameter: condition", event)

        # regex filter
        esc = re.escape(condition)
        filtered = df[df['normalized_names'].str.contains(esc, case=False, na=False, regex=True)]

        if filtered.empty:
            return build_response(f"No record found for '{condition}'", event)

        # formatting
        if display_mode == 'row-wise':
            body = f"Row-wise results for '{condition}':\n" + filtered.to_string(index=False)
        else:
            # decide columns
            all_cols = [col for col in df.columns if re.match(r'^P\d+$', col)]
            cols = all_cols if selected_column.lower() == 'all' else [selected_column]
            responses = []
            for _, row in filtered.iterrows():
                entries = []
                for col in cols:
                    if col in row and pd.notna(row[col]):
                        entries.append(f"{col}: {row[col]}")
                if entries:
                    responses.append(f"Data Point Name: {row['datapointnames']} | " + " | ".join(entries))
            body = (
                f"Plan Column-wise responses for '{condition}':\n" + "\n".join(responses)
                if responses else f"No matching records found in '{selected_column}' for '{condition}'."
            )

        return build_response(body, event)

    except RuntimeError as ce:
        logger.error(str(ce))
        return build_response(str(ce), event)
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
                    "TEXT": {"body": answer_text}
                }
            }
        },
        "sessionAttributes": event.get("sessionAttributes", {}),
        "promptSessionAttributes": event.get("promptSessionAttributes", {})
    }
