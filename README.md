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
        body = json.loads(event.get('body', '{}'))
        user_input = body.get('message') or body.get('prompt')
        if not user_input:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing message/prompt in request body'})
            }

        session_id = body.get('sessionId') or context.aws_request_id

        def call_agent(prompt):
            """Invoke the Bedrock agent; may raise ClientError."""
            return bedrock_agent.invoke_agent(
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

        # Attempt #1
        try:
            response = call_agent(user_input)
            status = response.get('ResponseMetadata', {}).get('HTTPStatusCode', 500)
        except ClientError as e:
            # If it's a dependencyFailedException, treat like a non-200
            error_code = e.response.get('Error', {}).get('Code')
            status = 500
            print(f"InvokeAgent failed with {error_code}: {e}")
            response = None

        # If we failed or got non-200, strip and retry once
        if status != 200:
            stripped = re.sub(r'\bcolumn-wise\s+P\d+\b', '', user_input, flags=re.IGNORECASE).strip()
            if stripped and stripped != user_input:
                try:
                    print(f"Retrying with stripped input: {stripped}")
                    response = call_agent(stripped)
                    status = response.get('ResponseMetadata', {}).get('HTTPStatusCode', 500)
                except ClientError as e:
                    print(f"Second InvokeAgent failed: {e}")
                    # Let response remain None or previous
                    response = None

        if not response or status != 200:
            # Final failure
            return {
                'statusCode': 502,
                'body': json.dumps({'error': 'Bedrock invoke_agent failed after retry'})
            }

        # Build the completion and citations
        completion = ""
        citations = []
        for ev in response.get('completion', []):
            chunk = ev.get('chunk', {})
            if 'bytes' in chunk:
                completion += chunk['bytes'].decode('utf-8')
            if 'attribution' in chunk and 'citations' in chunk['attribution']:
                for c in chunk['attribution']['citations']:
                    ref = c['retrievedReferences'][0]
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
        print(f"Unhandled error: {e}")
        traceback.print_exc()
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'stackTrace': traceback.format_exc()
            })
        }
