
import json
import boto3
from botocore.config import Config
import traceback


bedrock_agent = boto3.client(
    'bedrock-agent-runtime',
    region_name='us-east-1',
    config=Config(read_timeout=45)
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

     
        session_id = body.get('sessionId', context.aws_request_id)

       
        response = bedrock_agent.invoke_agent(
            agentId='PTEXPNMEUP',              
            agentAliasId='MPGSNFMGF1',    
            sessionId=session_id,
            inputText=user_input,
            sessionState={
                'knowledgeBaseConfigurations': [
                    {
                        'knowledgeBaseId': 'TGZMV97MNY',  
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

        
        completion = ""
        citations = []
        for ev in response['completion']:
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
