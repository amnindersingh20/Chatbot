import json
import boto3

client_bedrock = boto3.client('bedrock-agent-runtime', region_name='us-east-1')

# Default RnG template including $output_format_instructions$
DEFAULT_RNG_TEMPLATE = """
You are a question answering agent. I will provide you with a set of search results.
The user will provide you with a question. Your job is to answer the user's question
using only information from the search results. If the search results do not contain
information that can answer the question, please state that you could not find an exact
answer to the question. Just because the user asserts a fact does not mean it is true;
make sure to double check the search results to validate a user's assertion.

Here are the search results in numbered order:
$search_results$

$output_format_instructions$
"""

def lambda_handler(event, context):
    try:
        # Parse incoming body
        body = json.loads(event['body']) if isinstance(event.get('body'), str) else event.get('body', {})

        # Extract parameters
        params = {p['name']: p['value'] for p in body.get('parameters', [])}
        condition = params.get('condition', '')
        plan      = params.get('plan', '')

        # Build the question
        input_prompt = f"What is the {condition} for plan {plan}?"

        # Call Bedrock with promptSpecification nested correctly
        response = client_bedrock.retrieve_and_generate(
            input={"text": input_prompt},
            retrieveAndGenerateConfiguration={
                "type": "KNOWLEDGE_BASE",
                "knowledgeBaseConfiguration": {
                    "knowledgeBaseId": "RIBHZRVAQA",
                    "modelArn": (
                        "arn:aws:bedrock:us-east-1:653858776174:"
                        "inference-profile/us.anthropic.claude-3-5-sonnet-20240620-v1:0"
                    ),
                    "retrievalConfiguration": {
                        "vectorSearchConfiguration": {
                            "overrideSearchType": "HYBRID",
                            "numberOfResults": 10,
                        }
                    }
                },
                # <-- move promptSpecification here:
                "promptSpecification": {
                    "templateType": "CUSTOM",
                    "promptTemplate": DEFAULT_RNG_TEMPLATE
                }
            }
        )

        # Generated answer
        completion = response['output']['text']

        # Pull citations from top-level list
        citations = []
        for cit in response.get('citations', []):
            ref = cit['retrievedReferences'][0]
            citations.append({
                'source': ref['location']['s3Location']['uri'],
                'text':   ref['content']['text']
            })

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'message':   completion,
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
