import logging
import json
import re
import difflib
from io import StringIO
import boto3
import pandas as pd

log = logging.getLogger()
log.setLevel(logging.INFO)

S3_BUCKET = "poai"
S3_KEY = "2ting.csv"
FALLBACK_LAMBDA_NAME = "Poda1"
BEDROCK_MODEL_ID = "anthropic.claude-3-5-sonnet-20240620-v1:0"

_s3 = boto3.client('s3')
_lambda = boto3.client('lambda')
_bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

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

        df['Data Point Name'] = df['Data Point Name'].astype(str).str.replace('–', '-', regex=False)\
                                                          .str.replace('\u200b', '', regex=False)\
                                                          .str.strip().str.lower()
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

def summarize_with_claude35(composite_result: list) -> str:
    try:
        user_prompt = f"""
You are a helpful and friendly health benefits advisor responding to an employee who asked about health plan details. 
Below is a list of results from our internal search, each containing information for different plans.

{json.dumps(composite_result, indent=2)}

Your job:
- Summarize **each plan** separately, using *all* available details from the results.
- Clearly organize each plan’s section under its plan name (e.g., "Plan 1651").
- Within each plan, break down by:
    • **In-Network**: show separate details for **Individual** and **Family**
    • **Out-of-Network**: same—**Individual** and **Family**
- You should include info like deductibles, coinsurance, out-of-pocket maximums, etc., when available.
- Use natural, conversational language — imagine you're explaining it to a colleague who wants clarity, not formal policy text.
- Avoid jargon unless it's necessary, and give short clarifications when needed (e.g., "coinsurance means you pay 20% after deductible").
- Be concise but complete — each plan can take up to 4–6 lines if needed.
- End with a friendly closing inviting the employee to reach out with more questions.

Make sure nothing important from the data is skipped. Do not generalize; reflect real values.

Reply only with the final summary. Do not add explanations or notes outside the summary.
"""
        response = _bedrock.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "messages": [
                    {
                        "role": "user",
                        "content": user_prompt
                    }
                ],
                "max_tokens": 600,
                "temperature": 0.5
            })
        )
        body = json.loads(response['body'].read())
        return body['content'][0]['text']
    except Exception:
        log.exception("LLM summarization failed")
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
    log.info("Extracted parameters: %s", params)

    condition = None
    plans = []
    for p in params:
        if p.get("name") == "condition":
            condition = p.get("value")
        elif p.get("name") == "plan":
            plans.append(str(p.get("value")).strip())

    if not condition or not plans:
        missing = []
        if not condition: missing.append("condition")
        if not plans: missing.append("plan")
        return wrap_response(400, {"error": "Missing: " + ", ".join(missing)})

    composite = []
    for plan in plans:
        status, data = get_plan_value(condition, plan)
        if status != 200:
            return invoke_fallback(event)
        composite.append({"plan": plan, "data": data})

    summary = summarize_with_claude35(composite)

    return wrap_response(200, {
        "message": summary,
        "results": composite
    })
