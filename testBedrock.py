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

# DynamoDB history persistence
db_client = boto3.client('dynamodb', region_name='us-east-1')
class DynamoDBChatHistory:
    def __init__(self, table_name: str, session_id: str, client=None, region="us-east-1"):
        self.table_name = table_name
        self.session_id = session_id
        self.dynamo = client or boto3.client("dynamodb", region_name=region)
    def add_message(self, message: ChatMessage):
        timestamp = int(time.time() * 1000)
        created_at = datetime.now(timezone.utc).isoformat()
        self.dynamo.put_item(
            TableName=self.table_name,
            Item={
                "SessionId": {"S": self.session_id},
                "Timestamp": {"N": str(timestamp)},
                "CreatedAt": {"S": created_at},
                "MessageType": {"S": message.role},
                "Content": {"S": message.content},
            }
        )
    def clear(self):
        resp = self.dynamo.query(
            TableName=self.table_name,
            KeyConditionExpression="SessionId = :sid",
            ExpressionAttributeValues={":sid": {"S": self.session_id}},
            ProjectionExpression="SessionId, Timestamp"
        )
        with self.dynamo.batch_writer(TableName=self.table_name) as batch:
            for item in resp.get("Items", []):
                batch.delete_item(Key={"SessionId": item["SessionId"], "Timestamp": item["Timestamp"]})
    @property
    def messages(self):
        resp = self.dynamo.query(
            TableName=self.table_name,
            KeyConditionExpression="SessionId = :sid",
            ExpressionAttributeValues={":sid": {"S": self.session_id}},
            ScanIndexForward=True
        )
        return [ChatMessage(role=i["MessageType"]["S"], content=i["Content"]["S"]) for i in resp.get("Items", [])]

# S3 CSV lookup setup
S3_BUCKET = "pocbotai"
S3_KEY = "2025 Medical HPCC Combined.csv"
_s3 = boto3.client('s3')
SYNONYMS = {r"\bco[\s\-]?pay(ment)?s?\b": "copayment", r"\bco[\s\-]?insurance\b": "coinsurance",
            r"\b(oop|out[\s\-]?of[\s\-]?pocket)\b": "out of pocket", r"\bdeductible(s)?\b": "deductible"}

def normalize(text: str) -> str:
    return re.sub(r'[^a-z0-9]', '', str(text).lower())
def strip_filler(text: str) -> str:
    t = re.sub(r"[^\w\s]", "", text.lower().strip())
    for pat in [r"\bwhat('?s)?\b", r"\bwhat is\b", r"\bhelp me\b", r"\bmy\b"]:
        t = re.sub(pat, '', t).strip()
    return re.sub(r'\s+', ' ', t)
def expand_synonyms(text: str) -> str:
    for pat,rep in SYNONYMS.items(): text = re.sub(pat,rep,text,flags=re.IGNORECASE)
    return text
# load DF on cold start
try:
    obj = _s3.get_object(Bucket=S3_BUCKET,Key=S3_KEY)
    DF = pd.read_csv(StringIO(obj['Body'].read().decode()),dtype=str)
    DF.columns=DF.columns.str.strip()
    DF['Data Point Name']=DF['Data Point Name'].str.replace('–','-').str.replace('\u200b','').str.strip().str.lower()
    DF['normalized_name']=DF['Data Point Name'].apply(normalize)
except:
    logger.exception("CSV load failed")
    DF=pd.DataFrame()

def get_plan_value(raw: str, plan: str):
    s=strip_filler(raw); e=expand_synonyms(s); n=normalize(e)
    logger.info("Lookup: %s->%s->%s->%s",raw,s,e,n)
    if 'Data Point Name' not in DF or plan not in DF:
        return 500, f"Missing CSV column or plan {plan}"
    m=DF[DF['normalized_name'].str.contains(n,na=False)]
    if m.empty:
        close=difflib.get_close_matches(n,DF['normalized_name'],n=5,cutoff=0.7)
        m=DF[DF['normalized_name'].isin(close)] if close else m
    if m.empty: return 404, f"No match for '{raw}'"
    res=[]
    for _,r in m.iterrows():
        v=r.get(plan)
        if pd.notna(v): res.append({"condition":r['Data Point Name'],"plan":plan,"value":v})
    return (200,res) if res else (404,f"No value for '{raw}' plan {plan}")

# Fallback via Lambda
_lambda = boto3.client('lambda')
FALLBACK="Poc_Bot_lambda1"
def invoke_fallback(payload):
    resp=_lambda.invoke(FunctionName=FALLBACK,InvocationType='RequestResponse',Payload=json.dumps(payload).encode())
    return json.loads(resp['Payload'].read())

def wrap(status,body): return {"statusCode":status,"headers":{"Content-Type":"application/json","Access-Control-Allow-Origin":"*"},"body":json.dumps(body)}

# Lambda entry point
def lambda_handler(event,context):
    sid=event.get('headers',{}).get('Session-Id') or (event.get('queryStringParameters') or {}).get('session_id')
    if not sid: return wrap(400,{"error":"Missing session_id"})
    history=DynamoDBChatHistory("POC-Chsion",sid,db_client)

    raw=event.get('body') or '{}'
    try: payload=json.loads(raw)
    except: return wrap(400,{"error":"Invalid JSON"})

    # If parameters present → CSV lookup flow
    if payload.get('parameters'):
        q=payload.get('question','').strip() or 'lookup'
        history.add_message(ChatMessage(role='user',content=q))
        params=payload['parameters']
        if isinstance(params,dict): params=[{"name":k,"value":v} for k,v in params.items()]
        cond=next((p['value'] for p in params if p['name']=='condition'),None)
        plans=[str(p['value']) for p in params if p['name']=='plan']
        comp=[]
        for plan in plans:
            st,data=get_plan_value(cond,plan)
            if st!=200:
                out=invoke_fallback({"body":json.dumps(payload)})
                history.add_message(ChatMessage(role='assistant',content=json.dumps(out)))
                return wrap(200,out)
            comp.append({"plan":plan,"data":data})
        resp={"results":comp}
        history.add_message(ChatMessage(role='assistant',content=json.dumps(resp)))
        return wrap(200,resp)

    # Otherwise → fallback for any free-form chat
    msg=payload.get('question') or payload.get('message')
    if not msg: return wrap(400,{"error":"Missing question/message"})
    history.add_message(ChatMessage(role='user',content=msg))
    out=invoke_fallback({"body":json.dumps(payload)})
    history.add_message(ChatMessage(role='assistant',content=json.dumps(out)))
    return wrap(200,out)
