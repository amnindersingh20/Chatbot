import json
import re
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
import traceback

bedrock_agent = boto3.client(
    'bedrock-agent-runtime',
    region_name='us-east-1',
    config=Config(read_timeout=100)
)

APOLOGY_PATTERN = re.compile(
    r"I apologize, but I (?:couldn't|could not) find any specific information about",
    re.IGNORECASE
)

STRIP_PATTERN = re.compile(r'column-wise.*', re.IGNORECASE | re.DOTALL)

def invoke_and_check(prompt, session_id):
    print(f"[DEBUG invoke_and_check] entering with prompt: {prompt!r}")
    try:
        resp = bedrock_agent.invoke_agent(
            agentId='NE89PFJCD6',
            agentAliasId='FQE5SKICX5',
            sessionId=session_id,
            inputText=prompt,
            sessionState={
                'knowledgeBaseConfigurations': [{
                    'knowledgeBaseId': 'RIBHZRVAQA',
                    'retrievalConfiguration': {
                        'vectorSearchConfiguration': {
                            'overrideSearchType': 'HYBRID',
                            'numberOfResults': 100
                        }
                    }
                }]
            }
        )
        status = resp.get('ResponseMetadata', {}).get('HTTPStatusCode', 500)
        print(f"[DEBUG invoke_and_check] HTTP status: {status}")
        if status != 200:
            return False, "", [], f"HTTP {status}"
        
        completion = ""
        citations = []
        for ev in resp.get('completion', []):
            chunk = ev.get('chunk', {})
            if 'bytes' in chunk:
                completion += chunk['bytes'].decode('utf-8')
            for attr in chunk.get('attribution', {}).get('citations', []):
                ref = attr['retrievedReferences'][0]
                citations.append({
                    'source': ref['location']['s3Location']['uri'],
                    'text': ref['content']['text']
                })
        if APOLOGY_PATTERN.search(completion):
            print(f"[DEBUG invoke_and_check] apology detected in completion")
            return False, "", [], "apology detected"
        
        print(f"[DEBUG invoke_and_check] success, completion length {len(completion)}")
        return True, completion, citations, None

    except ClientError as e:
        code = e.response.get('Error', {}).get('Code')
        msg = e.response.get('Error', {}).get('Message')
        print(f"[DEBUG invoke_and_check] ClientError {code}: {msg}")
        return False, "", [], f"ClientError {code}: {msg}"
    except Exception as e:
        print(f"[DEBUG invoke_and_check] Exception: {e}")
        traceback.print_exc()
        return False, "", [], str(e)
    finally:
        print(f"[DEBUG invoke_and_check] exiting")

def make_response(status_code, body_dict):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps(body_dict)
    }

def lambda_handler(event, context):
    try:
        body = json.loads(event.get('body', '{}'))
        original_input = body.get('message') or body.get('prompt') or ""
        if not original_input:
            return make_response(400, {'error': 'Missing message/prompt in request body'})
        session_id = body.get('sessionId') or context.aws_request_id

        stripped_input = STRIP_PATTERN.sub('', original_input).strip()
        print(f"[DEBUG] Original input: {original_input!r}")
        print(f"[DEBUG] Stripped input: {stripped_input!r}")

        # Force two attempts: 1) original, 2) stripped (or original if strip empty)
        prompts = [original_input, stripped_input or original_input]

        last_error = None
        for idx, prompt in enumerate(prompts, start=1):
            print(f"[DEBUG] Attempt #{idx} with prompt: {prompt!r}")
            ok, completion, citations, reason = invoke_and_check(prompt, session_id)
            print(f"[DEBUG] Attempt #{idx} returned ok={ok}, reason={reason!r}")
            if ok:
                print(f"[DEBUG] Returning success from attempt #{idx}")
                return make_response(200, {
                    'message': completion,
                    'citations': citations,
                    'sessionId': session_id
                })
            last_error = reason
            print(f"[DEBUG] Attempt #{idx} failed, will {'continue' if idx==1 else 'stop'}")

        # If we exhaust both attempts
        print(f"[DEBUG] Both attempts failed, last_error={last_error!r}")
        return make_response(502, {
            'error': 'Bedrock invoke_agent failed after retries',
            'detail': last_error
        })

    except Exception as e:
        print(f"[DEBUG] Unhandled exception in lambda_handler: {e}")
        traceback.print_exc()
        return make_response(500, {
            'error': 'Internal server error in lambda_handler',
            'detail': str(e),
            'stackTrace': traceback.format_exc()
        })
