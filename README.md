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

# detect apology in the model’s text
APOLOGY_PATTERN = re.compile(
    r"I apologize, but I (?:couldn't|could not) find any specific information about",
    re.IGNORECASE
)

# strip "column-wise" + everything after it
STRIP_PATTERN = re.compile(r'column-wise.*', re.IGNORECASE | re.DOTALL)

def invoke_and_check(prompt, session_id):
    """
    Invoke the Bedrock agent once with `prompt`.  
    Returns (success: bool, completion_text: str, citations: list, error_reason: str).
    """
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
        if status != 200:
            return False, "", [], f"HTTP {status}"
        
        # assemble the completion
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
        
        # if it’s an apology, treat as a failure
        if APOLOGY_PATTERN.search(completion):
            return False, "", [], "apology detected"
        
        return True, completion, citations, None

    except ClientError as e:
        code = e.response.get('Error', {}).get('Code')
        msg = e.response.get('Error', {}).get('Message')
        return False, "", [], f"ClientError {code}: {msg}"
    except Exception as e:
        return False, "", [], str(e)


def lambda_handler(event, context):
    try:
        body = json.loads(event.get('body', '{}'))
        original_input = body.get('message') or body.get('prompt') or ""
        if not original_input:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing message/prompt in request body'})
            }
        session_id = body.get('sessionId') or context.aws_request_id

        # build stripped version once
        stripped_input = STRIP_PATTERN.sub('', original_input).strip()
        print(f"Original input: {original_input!r}")
        print(f"Stripped input: {stripped_input!r}")

        # 1) Try full prompt
        ok, completion, citations, reason = invoke_and_check(original_input, session_id)
        if not ok:
            print(f"Full-prompt attempt failed ({reason}); retrying with stripped prompt.")
            # 2) If stripped differs, try that next
            if stripped_input and stripped_input.lower() != original_input.lower():
                ok2, comp2, cit2, reason2 = invoke_and_check(stripped_input, session_id)
                if ok2:
                    completion, citations = comp2, cit2
                else:
                    # second attempt also failed
                    print(f"Stripped-prompt attempt also failed ({reason2})")
                    return {
                        'statusCode': 502,
                        'body': json.dumps({
                            'error': 'Bedrock invoke_agent failed after retries',
                            'detail': reason2
                        })
                    }
            else:
                # no meaningful stripped prompt to try
                return {
                    'statusCode': 502,
                    'body': json.dumps({
                        'error': 'No fallback prompt available; original attempt failed',
                        'detail': reason
                    })
                }

        # success path
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'message': completion,
                'citations': citations,
                'sessionId': session_id
            })
        }

    except Exception as e:
        print(f"Unhandled error in handler: {e}")
        traceback.print_exc()
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Internal server error in lambda_handler',
                'detail': str(e),
                'stackTrace': traceback.format_exc()
            })
        }
