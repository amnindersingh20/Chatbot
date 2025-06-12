import logging
import json
import re
import difflib
from io import StringIO
import boto3
import pandas as pd

log = logging.getLogger()
log.setLevel(logging.DEBUG)   # now log DEBUG-level messages

S3_BUCKET = "pocbotai"
S3_KEY = "2025 Medical SI HPCC for Chatbot Testing2.csv"
FALLBACK_LAMBDA_NAME = "Poc_Bot_lambda1"
BEDROCK_MODEL_ID = "anthropic.claude-3-5-sonnet-20240620-v1:0"

_s3 = boto3.client('s3')
_lambda = boto3.client('lambda')
_bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

SYNONYMS = {
    r"\bco[\s\-]?pay(ment)?s?\b": "copayment",
    r"\bco[\s\-]?insurance\b":      "coinsurance",
    r"\b(oop|out[\s\-]?of[\s\-]?pocket)\b": "out of pocket",
    r"\bdeductible(s)?\b":          "deductible"
}

def normalize(text: str) -> str:
    return re.sub(r'[^a-z0-9]', '', str(text).lower())

def strip_filler(text: str) -> str:
    text = re.sub(r"[^\w\s]", "", text.lower().strip())
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
        log.debug("Loading CSV from S3: %s/%s", S3_BUCKET, S3_KEY)
        obj = _s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
        df = pd.read_csv(StringIO(obj['Body'].read().decode('utf-8')), dtype=str)
        df.columns = df.columns.str.strip()
        log.debug("Raw columns: %s", df.columns.tolist())

        if 'Data Point Name' not in df.columns:
            raise KeyError("Missing 'Data Point Name' column")

        # normalize the Data Point Name column
        df['Data Point Name'] = (
            df['Data Point Name']
              .str.replace('–', '-', regex=False)
              .str.replace('\u200b', '', regex=False)
              .str.strip()
              .str.lower()
        )
        df['normalized_name'] = df['Data Point Name'].apply(normalize)
        log.debug("Sample normalized names: %s", df['normalized_name'].head().tolist())
        return df

    except Exception as e:
        log.exception("Failed to load CSV from S3")
        return pd.DataFrame()

DF = load_dataframe()

def get_plan_value(raw_condition: str, plan_id: str):
    stripped    = strip_filler(raw_condition)
    expanded    = expand_synonyms(stripped)
    query_norm  = normalize(expanded)

    log.debug("Lookup trace: raw=%r → stripped=%r → expanded=%r → norm=%r",
              raw_condition, stripped, expanded, query_norm)

    # check that the DataFrame and column exist
    if DF.empty:
        log.error("DataFrame is empty – CSV probably failed to load")
        return 500, "Internal error loading plan data"

    log.debug("Checking that plan '%s' is in columns: %s", plan_id, plan_id in DF.columns)
    if 'Data Point Name' not in DF.columns or plan_id not in DF.columns:
        log.error("Required column missing (Data Point Name or %s)", plan_id)
        return 500, f"CSV missing required columns or plan '{plan_id}'"

    # try exact substring match (no regex)
    matches = DF[DF['normalized_name'].str.contains(re.escape(query_norm), na=False, regex=True)]
    log.debug("Exact-substring matches count: %d", len(matches))

    # log any exact equality matches
    eq_matches = DF[DF['normalized_name'] == query_norm]
    log.debug("Exact equality matches count: %d", len(eq_matches))

    if matches.empty:
        # fallback to fuzzy
        all_names = DF['normalized_name'].tolist()
        close = difflib.get_close_matches(query_norm, all_names, n=5, cutoff=0.7)
        log.debug("Fuzzy candidates for '%s': %s", query_norm, close)
        matches = DF[DF['normalized_name'].isin(close)] if close else matches

    if matches.empty:
        log.warning("No data-points matching '%s' found at all", raw_condition)
        return 404, f"No data-points matching '{raw_condition}' found"

    # inspect values
    results = []
    for idx, row in matches.iterrows():
        val = row.get(plan_id)
        log.debug("Row #%s: condition=%s → raw value=%r", idx, row['Data Point Name'], val)
        if pd.notna(val):
            results.append({
                "condition": row['Data Point Name'],
                "plan": plan_id,
                "value": val
            })
        else:
            log.debug("Value for plan '%s' on row '%s' is empty/NaN", plan_id, row['Data Point Name'])

    if not results:
        log.error("Matched condition rows, but no non-null values under plan '%s'", plan_id)
        return 404, f"No value for '{raw_condition}' under plan '{plan_id}'"

    return 200, results

# … rest of your code unchanged …
