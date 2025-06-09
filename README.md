import json
import os
import boto3

client_bedrock = boto3.client('bedrock-agent-runtime', region_name='us-east-1')

# Extend this mapping up to 10 populationType → knowledgeBaseId entries
POPULATION_KB_MAP = {
    "ATMGMT": "RIBAQA",
    "BTMGMT": "2",
    # "CTMGMT": "3",
    # ... up to 10 entries
}

DEFAULT_RNG_TEMPLATE = """
You are a question answering agent. I will provide you with a set of search results.
The user will provide you with a question. Your job is to answer the user's question
using only information from the search results. You will only consider the current year and next year data to answer user's question. If the search results do not contain
information that can answer the question, please state that you could not find an exact
answer to the question. Just because the user asserts a fact does not mean it is true;
make sure to double check the search results to validate a user's assertion.

Here are the search results in numbered order:
$search_results$

$output_format_instructions$
"""

def lambda_handler(event, context):
    try:
        # parse JSON body
        body = json.loads(event['body']) if isinstance(event.get('body'), str) else event.get('body', {})

        # extract parameters into a dict
        params = { p['name']: p['value'] for p in body.get('parameters', []) }

        condition       = params.get('condition', '')
        plan            = params.get('plan', '')
        population_type = params.get('populationType', '')

        # pick the KB ID based on populationType, or use a default
        knowledge_base_id = POPULATION_KB_MAP.get(population_type, POPULATION_KB_MAP.get("DEFAULT", "RIBAQA"))

        # build your prompt
        input_prompt = f"What is the {condition} for plan {plan}?"

        # invoke Bedrock retrieve-and-generate
        response = client_bedrock.retrieve_and_generate(
            input={"text": input_prompt},
            retrieveAndGenerateConfiguration={
                "type": "KNOWLEDGE_BASE",
                "knowledgeBaseConfiguration": {
                    "knowledgeBaseId": knowledge_base_id,
                    "modelArn": (
                        "arn:aws:bedrock:us-east-1:74:"
                        "inference-profile/us.anthropic.claude-3-5-sonnet-20-v1:0"
                    ),
                    "retrievalConfiguration": {
                        "vectorSearchConfiguration": {
                            "overrideSearchType": "HYBRID",
                            "numberOfResults": 10,
                            "filter": {
                                "equals": {
                                    "key": "type",
                                    "value": "midwest CWA"
                                }
                            }
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

        # extract completion and citations
        completion = response['output']['text']
        citations = []
        for cit in response.get('citations', []):
            refs = cit.get('retrievedReferences', [])
            if not refs:
                continue
            ref = refs[0]
            citations.append({
                'source': ref['location']['s3Location']['uri'],
                'text':   ref['content']['text']
            })

        # return structured JSON
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json; charset=utf-8',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'message':   completion,
                'citations': citations
            }, indent=2)
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
