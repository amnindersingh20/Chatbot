import logging, json, re, difflib
from io import StringIO
import boto3, pandas as pd

log = logging.getLogger()
log.setLevel(logging.INFO)

S3_BUCKET = "pi"
S3_KEY = "2025 ng.csv"
FALLBACK_LAMBDA_NAME = "Poc_"

_s3      = boto3.client('s3')
_lambda  = boto3.client('lambda')
comprehend = boto3.client('comprehend')

SYNONYMS = {
    r"\bco[\s\-]?pay(ment)?s?\b"    : "copayment",
    r"\bco[\s\-]?insurance\b"       : "coinsurance",
    r"\b(oop|out[\s\-]?of[\s\-]?pocket)\b" : "out of pocket",
    r"\bdeductible(s)?\b"           : "deductible",   
}

def normalize(text: str) -> str:
    return re.sub(r'[^a-z0-9]', '', text.lower())

def strip_filler(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"^(what('?s)?|what is|is|tell me|give me|please show|how much is)\s+(my\s+)?", "", text).strip()
    log.info(f"After strip_filler: '{text}'")
    return text

def expand_synonyms(text: str) -> str:
    for pattern, repl in SYNONYMS.items():
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    log.info(f"After expand_synonyms: '{text}'")
    return text

def extract_key_phrase(text):
    try:
        result = comprehend.detect_entities(Text=text, LanguageCode="en")
        entities = result.get("Entities", [])
        if entities:
            sorted_entities = sorted(entities, key=lambda e: e["Score"], reverse=True)
            phrase = sorted_entities[0]["Text"]
            log.info(f"Extracted entity from Comprehend: '{phrase}'")
            return phrase
        return text
    except Exception as e:
        log.warning(f"Comprehend entity extraction failed: {e}")
        return text

def load_dataframe():
    try:
        obj = _s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
        df  = pd.read_csv(StringIO(obj['Body'].read().decode('utf-8')))
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
    log.info(f"Original query: '{raw_condition}'")
    
    stripped = strip_filler(raw_condition)
    key_phrase = extract_key_phrase(stripped)
    log.info(f"After Comprehend entity extraction: '{key_phrase}'")
    
    condition = expand_synonyms(key_phrase)
    query_norm = normalize(condition)
    log.info(f"Normalized query: '{query_norm}'")

    if 'Data Point Name' not in DF.columns or plan_id not in DF.columns:
        return 500, f"CSV missing required columns or plan '{plan_id}'"

    matches = DF[DF['normalized_name'].str.contains(query_norm, na=False)]

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
                "plan"     : plan_id,
                "value"    : val
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
            FunctionName   = FALLBACK_LAMBDA_NAME,
            InvocationType = "RequestResponse",
            Payload        = json.dumps(event_payload).encode()
        )
        return wrap_response(200, json.loads(resp['Payload'].read()))
    except Exception as e:
        log.exception("Fallback invocation failed")
        return wrap_response(500, {"error": f"Fallback error: {e}"})

def lambda_handler(event, _context):
    log.info("Received: \n%s", json.dumps(event, indent=4))
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
        plan      = p.get("plan")      or payload.get("plan")

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
                        {"name": "plan",      "value": plan}
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
                    {"name": "plan",      "value": p.get("plan", "")}
                ]
            })
        }
        return invoke_fallback(fb_event)
