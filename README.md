import logging
import json
import re
import difflib
from io import StringIO
import boto3
import pandas as pd

log = logging.getLogger()
log.setLevel(logging.INFO)

S3_BUCKET = "pi"
S3_KEY = "2025 ng.csv"
FALLBACK_LAMBDA_NAME = "Poc_"

_s3 = boto3.client('s3')
_lambda = boto3.client('lambda')
_comprehend = boto3.client('comprehend')

SYNONYMS = {
    r"\bco[\s\-]?pay(ment)?s?\b": "copayment",
    r"\bco[\s\-]?insurance\b": "coinsurance",
    r"\b(oop|out[\s\-]?of[\s\-]?pocket)\b": "out of pocket",
    r"\bdeductible(s)?\b": "deductible",
}

def normalize(text: str) -> str:
    return re.sub(r'[^a-z0-9]', '', text.lower())

def strip_filler(text: str) -> str:
    text = text.lower().strip()
    starters = [
        r"what('?s)?",
        r"what is",
        r"tell me",
        r"give me",
        r"please show",
        r"how much is",
        r"could you please",
        r"can you",
        r"would you",
        r"do you know",
        r"is",
        r"show me",
        r"explain",
        r"i want to know",
        r"find out",
    ]
    starters_pattern = r"^(?:" + "|".join(starters) + r")"
    fillers_pattern = r"(?:\s+(?:please|my|the))*\s*"
    pattern = starters_pattern + fillers_pattern
    cleaned_text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
    cleaned_text = re.sub(r"[?.!]*$", "", cleaned_text).strip()
    return cleaned_text

def expand_synonyms(text: str) -> str:
    for pattern, repl in SYNONYMS.items():
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    return text

def extract_key_condition_with_comprehend(text: str) -> str:
    """
    Use AWS Comprehend to extract key phrases from the user input.
    Return the longest key phrase as the main condition.
    """
    try:
        response = _comprehend.detect_key_phrases(
            Text=text,
            LanguageCode='en'
        )
        phrases = [kp['Text'].lower() for kp in response.get('KeyPhrases', [])]
        if not phrases:
            return text  # fallback to raw text if no key phrases found
        # Choose the longest phrase assuming it’s most descriptive
        key_phrase = max(phrases, key=len)
        log.info(f"Extracted key phrase from Comprehend: '{key_phrase}'")
        return key_phrase
    except Exception as e:
        log.warning(f"Comprehend key phrase extraction failed: {e}")
        return text

def load_dataframe():
    try:
        obj = _s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
        df = pd.read_csv(StringIO(obj['Body'].read().decode('utf-8')))
        df.columns = df.columns.astype(str).str.strip()
        if 'Data Point Name' not in df.columns:
            raise KeyError("Missing 'Data Point Name'")
        df['Data Point Name'] = (
            df['Data Point Name']
              .astype(str)
              .str.replace('–', '-', regex=False)
              .str.replace('\u200b', '', regex=False)
              .str.strip()
              .str.lower()
        )
        df['normalized_name'] = df['Data Point Name'].apply(normalize)
        return df
    except Exception:
        log.exception("Failed to load CSV from S3")
        return pd.DataFrame()

DF = load_dataframe()

def get_plan_value(raw_condition: str, plan_id: str):
    plan_id = str(plan_id).strip()
    # Strip filler words first
    cleaned = strip_filler(raw_condition)
    # Extract key phrase using AWS Comprehend
    key_condition = extract_key_condition_with_comprehend(cleaned)
    # Expand synonyms after that
    condition = expand_synonyms(key_condition)
    query_norm = normalize(condition)

    log.info(f"Original query: '{raw_condition}'")
    log.info(f"After strip_filler: '{cleaned}'")
    log.info(f"After comprehend key phrase extraction: '{key_condition}'")
    log.info(f"After expand_synonyms: '{condition}'")
    log.info(f"Normalized query: '{query_norm}'")

    if 'Data Point Name' not in DF.columns or plan_id not in DF.columns:
        return 500, f"CSV missing required columns or plan '{plan_id}'"

    # Try substring match (contains)
    matches = DF[DF['normalized_name'].str.contains(query_norm, na=False)]

    # If no matches, try fuzzy matching with difflib
    if matches.empty:
        all_norms = DF['normalized_name'].tolist()
        ratios = difflib.get_close_matches(query_norm, all_norms, n=5, cutoff=0.7)
        if ratios:
            matches = DF[DF['normalized_name'].isin(ratios)]

    if matches.empty:
        return 404, f"No data-points matching '{raw_condition}' found"

    results = []
    for _, row in matches.iterrows():
        val = row.get(plan_id)
        if pd.notna(val):
            results.append({
                "condition": row['Data Point Name'],
                "plan": plan_id,
                "value": val
            })

    if not results:
        return 404, f"No value for '{raw_condition}' under plan '{plan_id}'"

    return 200, results

def wrap_response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "OPTIONS,POST"
        },
        "body": json.dumps(body)
    }

def invoke_fallback(event_payload):
    try:
        resp = _lambda.invoke(
            FunctionName=FALLBACK_LAMBDA_NAME,
            InvocationType="RequestResponse",
            Payload=json.dumps(event_payload).encode()
        )
        return wrap_response(200, json.loads(resp['Payload'].read()))
    except Exception as e:
        log.exception("Fallback invocation failed")
        return wrap_response(500, {"error": f"Fallback error: {e}"})

def lambda_handler(event, _context):
    log.info("Received: %s", json.dumps(event))
    try:
        raw = event.get("body") or event.get("prompt") or "{}"
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode()
        payload = json.loads(raw) if isinstance(raw, str) else raw

        params = payload.get("parameters") or []
        if isinstance(params, dict):
            params = [{"name": k, "value": v} for k, v in params.items()]
        p = {d["name"]: d["value"] for d in params if "name" in d and "value" in d}
        condition = p.get("condition") or payload.get("condition")
        plan = p.get("plan") or payload.get("plan")

        if not condition or not plan:
            missing = [k for k in ("condition", "plan") if not locals()[k]]
            return wrap_response(400, {"error": f"Missing: {', '.join(missing)}"})

        status, data = get_plan_value(condition, plan)
        if status == 200:
            return wrap_response(200, data)
        else:
            log.warning("Primary lookup failed (%s). Invoking fallback.", status)
            fb_event = {
                "body": json.dumps({
                    "parameters": [
                        {"name": "condition", "value": condition},
                        {"name": "plan", "value": plan}
                    ]
                })
            }
            return invoke_fallback(fb_event)

    except Exception as e:
        log.exception("Unhandled error")
        fb_event = {
            "body": json.dumps({
                "parameters": [
                    {"name": "condition", "value": p.get("condition", "")},
                    {"name": "plan", "value": p.get("plan", "")}
                ]
            })
        }
        return invoke_fallback(fb_event)
