import logging
import json
import re
import difflib
from io import StringIO
import boto3
import pandas as pd
import io

# Configure logger
log = logging.getLogger()
log.setLevel(logging.INFO)

# Constants and clients
S3_BUCKET = "pocbotai"
S3_KEY = "2025 Medical SI HPCC for Chatbot Testing.csv"
FALLBACK_LAMBDA_NAME = "Poc_Bot_lambda1"
BEDROCK_MODEL_ID = "anthropic.claude-3-5-sonnet-20240620-v1:0"

_s3 = boto3.client('s3')
_lambda = boto3.client('lambda')
_bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

# In-memory session store
memory_store = {}

# Synonym mapping
SYNONYMS = {
    r"\bco[\s\-]?pay(ment)?s?\b": "copayment",
    r"\bco[\s\-]?insurance\b": "coinsurance",
    r"\b(oop|out[\s\-]?of[\s\-]?pocket)\b": "out of pocket",
    r"\bdeductible(s)?\b": "deductible"
}

# Text normalization utilities
def normalize(text: str) -> str:
    return re.sub(r'[^a-z0-9]', '', str(text).lower())

def strip_filler(text: str) -> str:
    text = re.sub(r"[^\w\s]", "", text.lower().strip())
    fillers = [
        r"\bwhat('?s)?\b", r"\bwhats\b", r"\bwhat is\b", r"\btell me\b",
        r"\bgive me\b", r"\bplease show\b", r"\bhow much is\b", r"\bis\b", r"\bmy\b"
    ]
    for pat in fillers:
        text = re.sub(pat, '', text).strip()
    return re.sub(r'\s+', ' ', text)

def expand_synonyms(text: str) -> str:
    for pat, rep in SYNONYMS.items():
        text = re.sub(pat, rep, text, flags=re.IGNORECASE)
    return text

# Load CSV from S3 into a DataFrame
def load_dataframe():
    try:
        obj = _s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
        df = pd.read_csv(StringIO(obj['Body'].read().decode('utf-8')), dtype=str)
        df.columns = df.columns.str.strip()

        if 'Data Point Name' not in df.columns:
            raise KeyError("Missing 'Data Point Name' column")

        df['Data Point Name'] = (
            df['Data Point Name'].astype(str)
            .str.replace('–', '-', regex=False)
            .str.replace('\u200b', '', regex=False)
            .str.strip().str.lower()
        )
        df['normalized_name'] = df['Data Point Name'].apply(normalize)
        return df

    except Exception:
        log.exception("Failed to load CSV from S3")
        return pd.DataFrame()

DF = load_dataframe()

# Lookup plan value
def get_plan_value(raw_condition: str, plan_id: str):
    stripped = strip_filler(raw_condition)
    expanded = expand_synonyms(stripped)
    query_norm = normalize(expanded)

    log.info("Lookup trace: raw=%r → stripped=%r → expanded=%r → norm=%r", raw_condition, stripped, expanded, query_norm)

    if 'Data Point Name' not in DF.columns or plan_id not in DF.columns:
        return 500, f"CSV missing required columns or plan '{plan_id}'"

    matches = DF[DF['normalized_name'].str.contains(query_norm, na=False)]
    log.info("Exact matches: %d", len(matches))

    if matches.empty:
        close = difflib.get_close_matches(query_norm, DF['normalized_name'].tolist(), n=5, cutoff=0.7)
        log.info("Fuzzy matches: %s", close)
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

# Summarization via Claude 3.5
... (unchanged summarization and fallback/invoke functions) ...

# Wrapper for HTTP response
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

# Lambda handler with rich logging and error handling
def lambda_handler(event, _context):
    log.info("Received event payload: %s", json.dumps(event))
    try:
        # Parse body or prompt
        raw = event.get("body") or event.get("prompt") or "{}"
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode()
        payload = json.loads(raw) if isinstance(raw, str) else raw

        # Normalize parameters
        params = payload.get("parameters") or []
        if isinstance(params, dict):
            params = [{"name": k, "value": v} for k, v in params.items()]

        condition = None
        plans = []
        for p in params:
            if p.get("name") == "condition":
                condition = p.get("value")
            elif p.get("name") == "plan":
                plans.append(str(p.get("value")).strip())

        available_options = payload.get("availableOptions", [])
        elected_option = payload.get("electedOption")
        session_id = payload.get("sessionId", "default-session")

        log.info("Parsed parameters → condition=%s plans=%s", condition, plans)
        log.info("availableOptions=%s electedOption=%s sessionId=%s", available_options, elected_option, session_id)

        # Validate
        missing = []
        if not condition:
            missing.append("condition")
        if not plans:
            missing.append("plan")
        if missing:
            return wrap_response(400, {"error": "Missing: " + ", ".join(missing)})

        # Build plan description map
        plan_desc_map = {str(opt.get("optionId")): opt.get("optionDescription") for opt in available_options}
        if isinstance(elected_option, dict):
            plan_desc_map[str(elected_option.get("optionId"))] = elected_option.get("optionDescription")
        log.info("Plan → Description map: %s", plan_desc_map)

        # Lookup each plan
        composite = []
        for plan in plans:
            log.info("Looking up plan '%s' for condition '%s'", plan, condition)
            status, data = get_plan_value(condition, plan)
            log.info("get_plan_value returned status=%s data=%s", status, data)
            if status != 200:
                log.warning("Bad status for plan '%s', invoking fallback", plan)
                return invoke_fallback(event)
            composite.append({
                "planId": plan,
                "results": data
            })

        log.info("Composite results assembled: %s", composite)

        # Summarize
        summary = summarize_with_claude35_streaming(session_id, composite, available_options, elected_option)
        log.info("Summarizer returned: %s", summary)

        return wrap_response(200, {"summary": summary})

    except Exception:
        log.exception("Unhandled exception in lambda_handler")
        return wrap_response(500, {"error": "Internal server error"})
