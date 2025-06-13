import json
import os
import boto3
import logging

log = logging.getLogger()
log.setLevel(logging.INFO)

client_bedrock = boto3.client('bedrock-agent-runtime', region_name='us-east-1')

POPULATION_KB_MAP = {
    "ATMGMT": "RIBHQA",
    "BTMGMT": "TGZMMNY",
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
        # Parse out the JSON body
        raw_body = event.get('body', {}) 
        body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body

        # Extract parameters as a dict
        params = { p['name']: p['value'] for p in body.get('parameters', []) }

        condition          = params.get('condition', '')
        option_description = params.get('optionDescription', '')
        population_type    = params.get('populationType', '')

        # Choose the correct KB based on population type
        knowledge_base_id = POPULATION_KB_MAP.get(population_type, POPULATION_KB_MAP.get("DEFAULT", "RIBAQA"))

        # Build the prompt using the human‑readable description
        input_prompt = f"What is the {condition} for the option “{option_description}”?"

        log.info("Fallback prompt: %s", input_prompt)

        # Invoke Bedrock retrieve-and-generate
        response = client_bedrock.retrieve_and_generate(
            input={"text": input_prompt},
            retrieveAndGenerateConfiguration={
                "type": "KNOWLEDGE_BASE",
                "knowledgeBaseConfiguration": {
                    "knowledgeBaseId": knowledge_base_id,
                    "modelArn": (
                        "arn:aws:bedrock:us-east-1:653858776174:"
                        "inference-profile/us.anthropic.claude-3-5-sonnet-20240620-v1:0"
                    ),
                    "retrievalConfiguration": {
                        "vectorSearchConfiguration": {
                            "overrideSearchType": "HYBRID",
                            "numberOfResults": 50
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

        # Extract the generated answer
        completion = response['output']['text']

        # Pull out any citations for transparency
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

        # Return code 200 with the text and citations
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
        log.exception("Missing parameter")
        return {
            'statusCode': 400,
            'body': json.dumps({'error': f'Missing parameter: {str(e)}'})
        }
    except Exception as e:
        log.exception("Fallback Lambda failed")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
