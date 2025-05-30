import logging, json, re, difflib
from io import StringIO
import boto3, pandas as pd

log = logging.getLogger()
log.setLevel(logging.INFO)

S3_BUCKET = "pocai"
S3_KEY    = "2025ing.csv"
FALLBACK_LAMBDA_NAME = "Poc1"

_s3     = boto3.client('s3')
_lambda = boto3.client('lambda')

SYNONYMS = {
    r"\bco[\s\-]?pay(ment)?s?\b"          : "copayment",
    r"\bco[\s\-]?insurance\b"             : "coinsurance",
    r"\b(oop|out[\s\-]?of[\s\-]?pocket)\b": "out of pocket",
    r"\bdeductible(s)?\b"                 : "deductible"
}

def normalize(text: str) -> str:
    return re.sub(r'[^a-z0-9]', '', text.lower())

def strip_filler(text: str) -> str:
    text = text.lower().strip()
    fillers = [r"\bwhat('?s)?\b", r"\bwhat is\b", r"\btell me\b",
               r"\bgive me\b", r"\bplease show\b", r"\bhow much is\b",
               r"\bis\b", r"\bmy\b"]
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
        df  = pd.read_csv(StringIO(obj['Body'].read().decode()), dtype=str)
        df.columns = df.columns.str.strip()
        df['Data Point Name'] = (
            df['Data Point Name']
              .str.replace('–', '-', regex=False)
              .str.replace('\u200b', '', regex=False)
              .str.strip()
              .str.lower()
        )
        df['normalized_name'] = df['Data Point Name'].apply(normalize)
        return df
    except Exception:
        log.exception("Failed to load CSV")
        return pd.DataFrame()

DF = load_dataframe()

def get_plan_value(raw_condition: str, plan_id: str):
    stripped = strip_filler(raw_condition)
    expanded = expand_synonyms(stripped)
    query_norm = normalize(expanded)

    if 'Data Point Name' not in DF.columns or plan_id not in DF.columns:
        return 500, f"CSV missing required columns or plan '{plan_id}'"

    matches = DF[DF['normalized_name'].str.contains(query_norm, na=False)]
    if matches.empty:
        close = difflib.get_close_matches(query_norm, DF['normalized_name'].tolist(),
                                          n=5, cutoff=0.7)
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
    log.info("Received event: %s", json.dumps(event))

    # 1. Pull raw body (might already be a dict)
    raw = event.get("body") or event.get("prompt") or "{}"
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode()
    payload = json.loads(raw) if isinstance(raw, str) else raw

    # 2. Extract parameters list
    params = payload.get("parameters") or []
    if isinstance(params, dict):
        params = [{"name": k, "value": v} for k, v in params.items()]

    # 3. Separate out condition + all plans
    condition = None
    plans     = []
    for p in params:
        n = p.get("name")
        v = p.get("value")
        if n == "condition":
            condition = v
        elif n == "plan":
            plans.append(str(v).strip())

    if not condition or not plans:
        missing = []
        if not condition: missing.append("condition")
        if not plans:     missing.append("plan")
        return wrap_response(400, {"error": "Missing: " + ", ".join(missing)})

    # 4. Loop over each plan
    composite = []
    for plan in plans:
        status, data = get_plan_value(condition, plan)

        # --- transform 404 “no data-points” into “Not applicable” ---
        if status == 404 and data.startswith("No data-points matching"):
            composite.append({
                "plan": plan,
                "value": "Not applicable"
            })
            continue

        if status == 200:
            composite.append({
                "plan": plan,
                "data": data
            })
        else:
            # other errors → fallback per-plan, or include error
            composite.append({
                "plan": plan,
                "error": data
            })

    return wrap_response(200, composite)
