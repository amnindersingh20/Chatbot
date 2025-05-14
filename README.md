import json
import boto3
from botocore.config import Config
import traceback


bedrock_agent = boto3.client(
    'bedrock-agent-runtime',
    region_name='us-east-1',
    config=Config(read_timeout=45)
    
def lambda_handler(event, context):
    try:
        body = json.loads(event.get('body', '{}'))
        user_input = body.get('message') or body.get('prompt')
        if not user_input:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing message/prompt in request body'})
            }

        # Use provided sessionId or generate new one
        session_id = body.get('sessionId', context.aws_request_id)
        
        # Get sessionState from request or initialize with KB config
        session_state = body.get('sessionState')
        if not session_state:
            session_state = {
                'knowledgeBaseConfigurations': [{
                    'knowledgeBaseId': 'TGZ90',
                    'retrievalConfiguration': {
                        'vectorSearchConfiguration': {
                            'overrideSearchType': 'HYBRID',
                            'numberOfResults': 100
                        }
                    }
                }]
            }

        # Invoke agent with current session state
        response = bedrock_agent.invoke_agent(
            agentId='Pro',
            agentAliasId='MP0',
            sessionId=session_id,
            inputText=user_input,
            sessionState=session_state
        )

        # Process response stream
        completion = ""
        citations = []
        new_session_state = None
        
        for event in response.get('events', []):
            if 'chunk' in event:
                chunk = event['chunk']
                completion += chunk.get('bytes', b'').decode('utf-8')
            elif 'attribution' in event:
                for citation in event['attribution'].get('citations', []):
                    for ref in citation.get('retrievedReferences', []):
                        citations.append({
                            'source': ref.get('location', {}).get('s3Location', {}).get('uri', ''),
                            'text': ref.get('content', {}).get('text', '')
                        })
            elif 'sessionState' in event:
                new_session_state = event['sessionState']

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'message': completion,
                'citations': citations,
                'sessionId': session_id,
                'sessionState': new_session_state
            })
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        traceback.print_exc()
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'stackTrace': traceback.format_exc()
            })
        }
