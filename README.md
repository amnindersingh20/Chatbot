import logging
import json
import re
import difflib
from io import StringIO
import boto3
import pandas as pd

log = logging.getLogger()
log.setLevel(logging.INFO)

S3_BUCKET = "poi"
S3_KEY    = "20ing.csv"
FALLBACK_LAMBDA_NAME = "Poda1"
BEDROCK_MODEL_ID     = "your-bedrock-model-id"  # ← replace with your model ID

_s3       = boto3.client('s3')
_lambda   = boto3.client('lambda')
_bedrock  = boto3.client('bedrock-runtime')    # or region-specific endpoint

SYNONYMS = {
    r"\bco[\s\-]?pay(ment)?s?\b"          : "copayment",
    r"\bco[\s\-]?insurance\b"             : "coinsurance",
    r"\b(oop|out[\s\-]?of[\s\-]?pocket)\b": "out of pocket",
    r"\bdeductible(s)?\b"                 : "deductible"
}

def normalize(text: str) -> str:
    return re.sub(r'[^a-z0-9]', '', str(text).lower())

def strip_filler(text: str) -> str:
    text = re.sub(r"[^\w\s]", "", str(text).lower()).strip()
    fillers = [
        r"\bwhat('?s)?\b", r"\bwhats\b", r"\bwhat is\b", r"\btell me\b",
        r"\bgive me\b", r"\bplease show\b", r"\bhow much is\b",
        r"\bis\b", r"\bmy\b"
    ]
    for pat in fillers:
        text = re.sub(pat, '', text).strip()
    return re.sub(r'\s+', ' ', text)

def expand_synonyms(text: str) -> str:
    for pat, rep in SYNONYMS.items():
        text = re.sub(pat, rep, text, flags=re.IGNORECASE)
    return text

def load_dataframe():
    try:
        obj = _s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
        df  = pd.read_csv(StringIO(obj['Body'].read().decode('utf-8')), dtype=str)
        df.columns = df.columns.str.strip()
        if 'Data Point Name' not in df.columns:
            raise KeyError("Missing 'Data Point Name' column")
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
    stripped   = strip_filler(raw_condition)
    expanded   = expand_synonyms(stripped)
    query_norm = normalize(expanded)

    log.info("Lookup trace for %r → stripped=%r, expanded=%r, normalized=%r",
             raw_condition, stripped, expanded, query_norm)

    if 'Data Point Name' not in DF.columns or plan_id not in DF.columns:
        return 500, f"CSV missing required columns or plan '{plan_id}'"

    matches = DF[DF['normalized_name'].str.contains(query_norm, na=False)]
    log.info("Exact matches count for %r: %d", query_norm, len(matches))

    if matches.empty:
        close = difflib.get_close_matches(
            query_norm,
            DF['normalized_name'].tolist(),
            n=5,
            cutoff=0.7
        )
        log.info("Fuzzy-match suggestions for %r: %s", query_norm, close)
        matches = DF[DF['normalized_name'].isin(close)] if close else matches

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

def summarize_with_llm(composite):
    # Build prompt
    prompt_parts = ["I have CSV lookup results for several plans:"]
    for c in composite:
        prompt_parts.append(f"- Plan {c['plan']}: {json.dumps(c['data'])}")
    prompt_parts.append("\nPlease give me a short summary in this format:")
    prompt_parts.append("- Available options are: …")
    prompt_parts.append("- Elected options are: …\n")
    prompt = "\n".join(prompt_parts)

    # Call Bedrock
    resp = _bedrock.invoke_model(
        modelId    = BEDROCK_MODEL_ID,
        contentType= "application/json",
        accept     = "application/json",
        body       = json.dumps({
            "prompt":      prompt,
            "maxTokens":   200,
            "temperature": 0.2
        })
    )
    body = json.loads(resp["body"])
    return body.get("completion", "")

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
    log.info("Invoking fallback Lambda %r…", FALLBACK_LAMBDA_NAME)
    try:
        resp = _lambda.invoke(
            FunctionName   = FALLBACK_LAMBDA_NAME,
            InvocationType = "RequestResponse",
            Payload        = json.dumps(event_payload).encode()
        )
        return wrap_response(200, json.loads(resp['Payload'].read()))
    except Exception as e:
        log.exception("Fallback invocation failed")
        return wrap_response(500, {"error": f"Fallback error: {e}"})

def lambda_handler(event, _context):
    log.info("Received event: %s", json.dumps(event))

    # Parse body
    raw = event.get("body") or event.get("prompt") or "{}"
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode()
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        log.exception("Failed to parse JSON body")
        return wrap_response(400, {"error": "Invalid JSON in body"})

    # Extract parameters
    params = payload.get("parameters") or []
    if isinstance(params, dict):
        params = [{"name": k, "value": v} for k, v in params.items()]
    log.info("Extracted parameters: %s", params)

    condition = None
    plans     = []
    for p in params:
        if p.get("name") == "condition":
            condition = p.get("value")
        elif p.get("name") == "plan":
            plans.append(str(p.get("value")).strip())
    log.info("Condition: %r, Plans: %s", condition, plans)

    if not condition or not plans:
        missing = []
        if not condition: missing.append("condition")
        if not plans:     missing.append("plan")
        return wrap_response(400, {"error": "Missing: " + ", ".join(missing)})

    # Perform CSV lookups
    composite = []
    for plan in plans:
        status, data = get_plan_value(condition, plan)
        if status != 200:
            log.warning("Lookup failed for plan=%s → %s; invoking fallback", plan, data)
            return invoke_fallback(event)
        composite.append({"plan": plan, "data": data})

    # Summarize only the CSV results with Bedrock
    summary = summarize_with_llm(composite)

    return wrap_response(200, {
        "rawResults": composite,
        "summary":    summary
    })
