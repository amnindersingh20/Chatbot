import os
import time
import logging
import json
import re
difflib
from io import StringIO
import boto3
import pandas as pd
from datetime import datetime, timezone
from langchain.schema import ChatMessage

# Environment and AWS clients
os.environ.setdefault("AWS_PROFILE", "Amnder-2")
os.environ.setdefault("AWS_REGION", "us-east-1")
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# DynamoDB for history persistence
db_client = boto3.client('dynamodb', region_name='us-east-1')
class DynamoDBChatHistory:
    def __init__(self, table_name, session_id, client=None, region="us-east-1"):
        self.table_name = table_name
        self.session_id = session_id
        self.dynamo = client or boto3.client("dynamodb", region_name=region)
    def add_message(self, message: ChatMessage):
        ts = int(time.time() * 1000)
        created = datetime.now(timezone.utc).isoformat()
        self.dynamo.put_item(TableName=self.table_name, Item={
            "SessionId": {"S": self.session_id},
            "Timestamp": {"N": str(ts)},
            "CreatedAt": {"S": created},
            "MessageType": {"S": message.role},
            "Content": {"S": message.content},
        })
    @property
    def messages(self):
        resp = self.dynamo.query(
            TableName=self.table_name,
            KeyConditionExpression="SessionId = :sid",
            ExpressionAttributeValues={":sid": {"S": self.session_id}},
            ScanIndexForward=True
        )
        return [ChatMessage(role=i["MessageType"]["S"], content=i["Content"]["S"]) for i in resp.get("Items", [])]

# AWS Bedrock client for summarization fallback
_lambda = boto3.client('lambda')
bedrock_client = boto3.client('bedrock-runtime', region_name='us-east-1')
FALLBACK_LAMBDA = "Poc_Bot_lambda1"
BEDROCK_MODEL = "anthropic.claude-3-5-sonnet-20240620-v1:0"

# CSV lookup (cold start)
S3_BUCKET, S3_KEY = "pocbotai", "2025 Medical HPCC Combined.csv"
_s3 = boto3.client('s3')
SYN = {
    r"\bco[\s\-]?pay(ment)?s?\b": "copayment",
    r"\bco[\s\-]?insurance\b": "coinsurance",
    r"\b(oop|out[\s\-]?of[\s\-]?pocket)\b": "out of pocket",
    r"\bdeductible(s)?\b": "deductible"
}

def normalize(t): return re.sub(r'[^a-z0-9]', '', t.lower())
def strip_filler(t):
    t = re.sub(r"[^\w\s]", "", t.lower()).strip()
    for p in [r"\bwhat('?s)?\b", r"\bwhat is\b", r"\bplease show\b", r"\bhelp me\b"]:
        t = re.sub(p, '', t).strip()
    return re.sub(r'\s+', ' ', t)
def expand_synonyms(t):
    for p,r in SYN.items(): t = re.sub(p, r, t, flags=re.IGNORECASE)
    return t
try:
    o = _s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
    DF = pd.read_csv(StringIO(o['Body'].read().decode()), dtype=str)
    DF.columns = DF.columns.str.strip()
    DF['Data Point Name'] = DF['Data Point Name'].str.replace('–','-').str.replace('\u200b','').str.lower().str.strip()
    DF['normalized_name'] = DF['Data Point Name'].apply(normalize)
except Exception:
    logger.exception("Failed loading CSV")
    DF = pd.DataFrame()

def get_plan_value(raw, plan):
    stripped = strip_filler(raw)
    expanded = expand_synonyms(stripped)
    norm = normalize(expanded)
    logger.info("Lookup trace: %s → %s → %s → %s", raw, stripped, expanded, norm)
    if 'Data Point Name' not in DF or plan not in DF.columns:
        return 500, f"Missing CSV data or plan '{plan}'"
    matches = DF[DF['normalized_name'].str.contains(norm, na=False)]
    if matches.empty:
        close = difflib.get_close_matches(norm, DF['normalized_name'].tolist(), n=5, cutoff=0.7)
        matches = DF[DF['normalized_name'].isin(close)] if close else matches
    if matches.empty:
        return 404, f"No data-points matching '{raw}'"
    results = []
    for _, row in matches.iterrows():
        val = row.get(plan)
        if pd.notna(val):
            results.append({
                "condition": row['Data Point Name'],
                "plan": plan,
                "value": val
            })
    return (200, results) if results else (404, f"No value for '{raw}' under '{plan}'")

# Summarize multiple-plan results via Claude Bedrock
def summarize_csv_results(composite):
    prompt = f"""
You are a helpful and friendly health benefits advisor.
Here are the retrieved plan data:
{json.dumps(composite, indent=2)}

Summarize each option as its own section, clearly marking the plan ID, and organizing In-Network vs Out-of-Network details when present. End with a call for further questions.
"""
    try:
        resp = bedrock_client.invoke_model(
            modelId=BEDROCK_MODEL,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1024,
                "temperature": 0.5
            })
        )
        body = json.loads(resp['body'].read())
        return body['content'][0]['text']
    except Exception:
        logger.exception("Summarization LLM failed")
        return None

# Fallback Lambda invocation for non-CSV answers
def invoke_fallback(payload):
    resp = _lambda.invoke(
        FunctionName=FALLBACK_LAMBDA,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode()
    )
    return json.loads(resp['Payload'].read())

# HTTP response wrapper
def wrap(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": json.dumps(body)
    }

# Main Lambda handler
def lambda_handler(event, context):
    # Identify session for persistence
    sid = (event.get('headers') or {}).get('Session-Id') or (event.get('queryStringParameters') or {}).get('session_id')
    if not sid:
        return wrap(400, {"error": "Missing session_id"})
    history = DynamoDBChatHistory("POC-Chsion", sid, db_client)

    # Parse payload
    raw = event.get('body') or '{}'
    try:
        payload = json.loads(raw)
    except Exception:
        return wrap(400, {"error": "Invalid JSON"})

    # CSV lookup flow
    params = payload.get('parameters')
    if params:
        question = payload.get('question', '').strip() or 'CSV lookup'
        history.add_message(ChatMessage(role='user', content=question))
        if isinstance(params, dict):
            params = [{"name": k, "value": v} for k, v in params.items()]
        condition = next((p['value'] for p in params if p['name'] == 'condition'), None)
        plans = [str(p['value']) for p in params if p['name'] == 'plan']
        composite = []
        for plan in plans:
            status, data = get_plan_value(condition, plan)
            if status != 200:
                # Missing CSV data → fallback lambda
                out = invoke_fallback({"body": json.dumps(payload)})
                history.add_message(ChatMessage(role='assistant', content=json.dumps(out)))
                return wrap(200, out)
            composite.append({"plan": plan, "data": data})

        # If multiple plan results, summarize via Claude
        if len(composite) > 1:
            summary = summarize_csv_results(composite)
            assistant_response = {"summary": summary, "results": composite}
        else:
            assistant_response = {"results": composite}

        history.add_message(ChatMessage(role='assistant', content=json.dumps(assistant_response)))
        return wrap(200, assistant_response)

    # Free-form chat → fallback lambda for model response
    message = payload.get('question') or payload.get('message')
    if not message:
        return wrap(400, {"error": "Missing question/message"})
    history.add_message(ChatMessage(role='user', content=message))
    response = invoke_fallback({"body": json.dumps(payload)})
    history.add_message(ChatMessage(role='assistant', content=json.dumps(response)))
    return wrap(200, response)
