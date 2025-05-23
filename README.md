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

def lambda_handler(event, context):
    try:
        # Parse input
        body = json.loads(event.get('body', '{}'))
        original_input = body.get('message') or body.get('prompt') or ""
        if not original_input:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing message/prompt in request body'})
            }
        session_id = body.get('sessionId') or context.aws_request_id

        # Prepare up to two attempts
        stripped_input = re.sub(r'\bcolumn-wise\s+P\d+\b', '', original_input, flags=re.IGNORECASE).strip()
        prompts = [original_input]
        if stripped_input and stripped_input.lower() != original_input.lower():
            prompts.append(stripped_input)

        response = None
        last_error = None

        for idx, prompt in enumerate(prompts, start=1):
            try:
                print(f"Attempt #{idx} with prompt: {prompt!r}")
                resp = bedrock_agent.invoke_agent(
                    agentId='NE89PFJCD6',
                    agentAliasId='LZK78CEF6B',
                    sessionId=session_id,
                    inputText=prompt,
                    sessionState={
                        'knowledgeBaseConfigurations': [
                            {
                                'knowledgeBaseId': 'RIBHZRVAQA',
                                'retrievalConfiguration': {
                                    'vectorSearchConfiguration': {
                                        'overrideSearchType': 'HYBRID',
                                        'numberOfResults': 100
                                    }
                                }
                            }
                        ]
                    }
                )
                status = resp.get('ResponseMetadata', {}).get('HTTPStatusCode', 500)
                print(f"Received HTTP status: {status}")
                if status == 200:
                    response = resp
                    break
                else:
                    last_error = f"Non-200 status: {status}"
            except ClientError as e:
                code = e.response.get('Error', {}).get('Code')
                msg = e.response.get('Error', {}).get('Message')
                print(f"ClientError on attempt #{idx}: {code} – {msg}")
                last_error = f"{code}: {msg}"
            except Exception as e:
                print(f"Unexpected exception on attempt #{idx}: {e}")
                traceback.print_exc()
                last_error = str(e)

        # If we still have no valid response, return error
        if response is None:
            return {
                'statusCode': 502,
                'body': json.dumps({
                    'error': 'Bedrock invoke_agent failed after retries',
                    'detail': last_error
                })
            }

        # Build the completion and citations
        completion = ""
        citations = []
        for ev in response.get('completion', []):
            chunk = ev.get('chunk', {})
            if 'bytes' in chunk:
                completion += chunk['bytes'].decode('utf-8')
            for attr in chunk.get('attribution', {}).get('citations', []):
                ref = attr['retrievedReferences'][0]
                citations.append({
                    'source': ref['location']['s3Location']['uri'],
                    'text': ref['content']['text']
                })

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
