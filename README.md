import json
import boto3
from botocore.config import Config
import traceback

# Initialize the Bedrock Agent client
bedrock_agent = boto3.client(
    'bedrock-agent-runtime',
    region_name='us-east-1',
    config=Config(read_timeout=45)
)

def lambda_handler(event, context):
    try:
        # Parse incoming request body
        body = json.loads(event.get('body', '{}'))
        user_input = body.get('message') or body.get('prompt')
        if not user_input:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing message/prompt in request body'})
            }

        # Use provided sessionId or fallback to AWS request ID
        session_id = body.get('sessionId', context.aws_request_id)

        # Prepare invocation parameters
        params = {
            'agentId': 'PTEXPNMEUP',               # Replace with your Agent ID
            'agentAliasId': 'MPGSNFMGF1',          # Replace with your Agent Alias ID
            'sessionId': session_id,
            'inputText': user_input,
            'sessionState': {
                'knowledgeBaseConfigurations': [
                    {
                        'knowledgeBaseId': 'TGZMV97MNY',  # Replace with your KB ID
                        'retrievalConfiguration': {
                            'vectorSearchConfiguration': {
                                'overrideSearchType': 'HYBRID',
                                'numberOfResults': 100
                            }
                        }
                    }
                ]
            },
            'generationConfiguration': {
                'inferenceConfig': {
                    'temperature': 0.5,
                    'topP': 0,
                    'topK': 100
                }
            },
            'orchestrationConfiguration': {
                'inferenceConfig': {
                    'temperature': 0.5,
                    'topP': 0,
                    'topK': 100
                }
            }
        }

        # Invoke the Bedrock Agent
        response = bedrock_agent.invoke_agent(**params)

        # Collect the streamed completion and any citations
        completion = ''
        citations = []
        for event_chunk in response.get('completion', []):
            chunk = event_chunk.get('chunk', {})
            if 'bytes' in chunk:
                completion += chunk['bytes'].decode('utf-8')
            if 'attribution' in chunk and 'citations' in chunk['attribution']:
                for citation in chunk['attribution']['citations']:
                    ref = citation['retrievedReferences'][0]
                    citations.append({
                        'source': ref['location']['s3Location']['uri'],
                        'text': ref['content']['text']
                    })

        # Return successful response
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
        print(f"Error invoking Bedrock Agent: {e}")
        traceback.print_exc()
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'stackTrace': traceback.format_exc()
            })
        }
