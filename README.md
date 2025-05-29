import json
import boto3
 
client_bedrock = boto3.client('bedrock-agent-runtime', region_name='us-east-1')
 
def lambda_handler(event, context):
    try:
        body = json.loads(event['body']) if isinstance(event['body'], str) else event['body']
 
        params = {p['name']: p['value'] for p in body.get('parameters', [])}
        condition = params.get('condition', '')
        plan = params.get('plan', '')
       
        input_prompt = f"What is the {condition} for plan {plan}?"
 
        knowledgebase_id = "RIBHZRVAQA"
 
        response = client_bedrock.retrieve_and_generate(
            input={"text": input_prompt},
            retrieveAndGenerateConfiguration={
                "type": "KNOWLEDGE_BASE",
                "knowledgeBaseConfiguration": {
                    "knowledgeBaseId": knowledgebase_id,
                    "modelArn": "arn:aws:bedrock:us-east-1:653858776174:inference-profile/us.anthropic.claude-3-5-sonnet-20240620-v1:0",
                    "retrievalConfiguration": {
                        "vectorSearchConfiguration": {
                            'overrideSearchType': 'HYBRID',
                            'numberOfResults': 10,
                        }
                    }
                }
            }
        )
 
        completion = response['output']['text']
 
        citations = []
        if 'citations' in response['output']:
            for c in response['output']['citations']:
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
                'citations': citations
            })
        }
 
    except KeyError as e:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': f'Missing parameter: {str(e)}'})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
