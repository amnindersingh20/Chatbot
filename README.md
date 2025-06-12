import logging
import json
import re
import difflib
from io import StringIO
import boto3
import pandas as pd
import io

log = logging.getLogger()
log.setLevel(logging.INFO)

S3_BUCKET = "pocbotai"
S3_KEY = "2025 Medical SI HPCC for Chatbot Testing.csv"
FALLBACK_LAMBDA_NAME = "Poc_Bot_lambda1"
BEDROCK_MODEL_ID = "anthropic.claude-3-5-sonnet-20240620-v1:0"

_s3 = boto3.client('s3')
_lambda = boto3.client('lambda')
_bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

memory_store = {}  # In-memory session store

SYNONYMS = {
    r"\bco[\s\-]?pay(ment)?s?\b": "copayment",
    r"\bco[\s\-]?insurance\b": "coinsurance",
    r"\b(oop|out[\s\-]?of[\s\-]?pocket)\b": "out of pocket",
    r"\bdeductible(s)?\b": "deductible"
}

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

def summarize_with_claude35_streaming(session_id: str, composite_result: list, options: list, elected: dict) -> str:
    options_list = [
        {"optionId": opt.get("optionId"), "optionDescription": opt.get("optionDescription")}
        for opt in options
    ]
    elected_desc = elected.get("optionDescription") if isinstance(elected, dict) else None

    prompt = f"""
You are a helpful and friendly health benefits advisor.
Here are the available options:
{json.dumps(options_list, indent=2)}
The employee elected: {elected_desc}.

Retrieved plan data:
{json.dumps(composite_result, indent=2)}

Your job:
- Summarize each available option as its own section, using its optionDescription.
- Clearly mark which option was elected and which are other available options.
- Within each section, organize In-Network (Individual, Family) and Out-of-Network (Individual, Family).
- Include details like deductibles, coinsurance, out-of-pocket maximums, etc.
- Do not display plan IDs in parentheses after the description.
- Do not display that you asked to summarize.
- Use conversational, reader-friendly language and end with a call for further questions.
"""

    # Retrieve or initialize conversation history
    messages = memory_store.get(session_id, [])
    messages.append({
        "role": "user",
        "content": [{"text": prompt}]
    })

    try:
        stream = _bedrock.converse_stream(
            modelId=BEDROCK_MODEL_ID,
            messages=messages
        )

        output = io.StringIO()
        for event in stream["stream"]:
            chunk = event.get("chunk", {})
            content = chunk.get("bytes", b"").decode("utf-8")
            if content:
                output.write(content)

        assistant_reply = output.getvalue()
        messages.append({
            "role": "assistant",
            "content": [{"text": assistant_reply}]
        })
        memory_store[session_id] = messages

        return assistant_reply
    except Exception:
        log.exception("Streaming summarization failed")
        return None

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
    log.info("Received event: %s", json.dumps(event))

    raw = event.get("body") or event.get("prompt") or "{}"
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode()
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        log.exception("Failed to parse JSON body")
        return wrap_response(400, {"error": "Invalid JSON in body"})

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

    if not condition or not plans:
        missing = []
        if not condition: missing.append("condition")
        if not plans: missing.append("plan")
        return wrap_response(400, {"error": "Missing: " + ", ".join(missing)})

    plan_desc_map = {str(opt.get("optionId")): opt.get("optionDescription") for opt in available_options}
    if isinstance(elected_option, dict):
        plan_desc_map[str(elected_option.get("optionId"))] = elected_option.get("optionDescription")

    composite = []
    for plan in plans:
        status, data = get_plan_value(condition, plan)
        if status != 200:
            return invoke_fallback(event)
        composite
