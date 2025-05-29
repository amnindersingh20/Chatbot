import json
import boto3

client_bedrock = boto3.client('bedrock-agent-runtime', region_name='us-east-1')

# … your DEFAULT_RNG_TEMPLATE here …

def lambda_handler(event, context):
    try:
        # parse body & build prompt (same as before)…
        body = json.loads(event['body']) if isinstance(event.get('body'), str) else event.get('body', {})
        params = { p['name']: p['value'] for p in body.get('parameters', []) }
        condition = params.get('condition', '')
        plan      = params.get('plan', '')
        input_prompt = f"What is the {condition} for plan {plan}?"

        # call Bedrock
        response = client_bedrock.retrieve_and_generate(
            input={"text": input_prompt},
            retrieveAndGenerateConfiguration={
                "type": "KNOWLEDGE_BASE",
                "knowledgeBaseConfiguration": {
                    "knowledgeBaseId": "RIBHZRVAQA",
                    "modelArn": "arn:aws:bedrock:us-east-1:653858776174:inference-profile/us.anthropic.claude-3-5-sonnet-20240620-v1:0",
                    "retrievalConfiguration": {
                        "vectorSearchConfiguration": {
                            "overrideSearchType": "HYBRID",
                            "numberOfResults": 10
                        }
                    },
                    "generationConfiguration": {
                        "promptTemplate": {
                            "textPromptTemplate": DEFAULT_RNG_TEMPLATE
                        }
                    }
                }
            }
        )

        # extract answer + citations
        answer    = response['output']['text']
        raw_cites = response.get('citations', [])
        cites     = []
        for c in raw_cites:
            ref = c['retrievedReferences'][0]
            cites.append(f"{ref['location']['s3Location']['uri']}: {ref['content']['text']}")

        # merge into one string so your front end needs no changes
        if cites:
            answer += "\n\nReferences:\n" + "\n".join(f"{i+1}. {txt}" for i, txt in enumerate(cites))

        # return exactly the same JSON shape your front end already expects
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'message': answer
            })
        }

    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
