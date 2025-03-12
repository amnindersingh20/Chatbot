import json
import boto3

client_bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')

def lambda_handler(event, context):
    try:
        # Parse input from API Gateway
        body = json.loads(event['body'])
        input_prompt = body['prompt']
        
        # Generate response
        response = client_bedrock.invoke_model(
            contentType='application/json',
            accept='application/json',
            modelId='anthropic.claude-3-sonnet-20240229-v1:0',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 200,
                "temperature": 0.9,
                "messages": [{
                    "role": "user",
                    "content": [{"type": "text", "text": input_prompt}]
                }]
            })
        )
        
        # Parse response
        response_body = json.loads(response['body'].read())
        output_text = response_body['content'][0]['text']

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'  # Required for CORS
            },
            'body': json.dumps({
                'response': output_text
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
