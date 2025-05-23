import json
import re
import boto3
from botocore.config import Config
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

        # Helper to call the agent
        def call_agent(prompt):
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

        # First attempt
        response = call_agent(user_input)
        status = response.get('ResponseMetadata', {}).get('HTTPStatusCode', 500)

        # If non-200, strip "column-wise P<digits>" and retry once
        if status != 200:
            # remove any occurrence of "column-wise P123"
            stripped_input = re.sub(r'\bcolumn-wise\s+P\d+\b', '', user_input, flags=re.IGNORECASE).strip()
            if stripped_input and stripped_input != user_input:
                response = call_agent(stripped_input)

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
        # Log and return errors
        print(f"Error: {str(e)}")
        traceback.print_exc()
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'stackTrace': traceback.format_exc()
            })
        }
