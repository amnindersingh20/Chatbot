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

# Base template: we'll inject the brevity or detail instructions per‐option
BASE_RNG_TEMPLATE = """
You are a question answering agent. I will provide you with a set of search results.
The user will provide you with a question. Your job is to answer the user's question
using only information from the search results. You will only consider the current year
and next year data to answer the user's question. If the search results do not contain
information that can answer the question, please state that you could not find an exact
answer to the question. Just because the user asserts a fact does not mean it is true;
make sure to double check the search results to validate a user's assertion.

Here are the search results in numbered order:
$search_results$

# Answer instructions:
$custom_instructions$

$output_format_instructions$
"""

def build_prompt(condition: str,
                 option_description: str,
                 custom_instructions: str) -> dict:
    """
    Returns the retrieve-and-generateConfiguration dict for this option.
    We'll replace $search_results$ and $custom_instructions$ via the Bedrock templating.
    """
    template = BASE_RNG_TEMPLATE.replace(
        "$custom_instructions$", custom_instructions
    )
    # Note: $search_results$ and $output_format_instructions$ are handled by Bedrock agent.
    return {
        "retrieveAndGenerateConfiguration": {
            "type": "KNOWLEDGE_BASE",
            "knowledgeBaseConfiguration": {
                "knowledgeBaseId": None,      # set below
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
                        "textPromptTemplate": template
                    }
                }
            }
        },
        "input": {"text": f"What is the {condition} for the option “{option_description}”?"}
    }

def lambda_handler(event, context):
    try:
        # 1. Parse incoming body
        raw_body = event.get('body', {}) 
        body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body

        # 2. Pull out parameters, availableOptions & electedOption
        params = { p['name']: p['value'] for p in body.get('parameters', []) }
        condition       = params.get('condition', '')
        population_type = params.get('populationType', '')

        available_options = body.get('availableOptions', [])
        elected_option    = body.get('electedOption', {})

        if not condition or not available_options:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': 'Missing required fields: condition and/or availableOptions'
                })
            }

        # 3. KB selection
        kb_id = POPULATION_KB_MAP.get(population_type,
                                     POPULATION_KB_MAP.get("DEFAULT", "RIBAQA"))

        # 4. For each option, build and call Bedrock
        results = []
        for opt in available_options:
            desc = opt.get('optionDescription', '')
            is_elected = (
                elected_option
                and opt.get('optionId') == elected_option.get('optionId')
            )

            # custom instructions per‐option
            if is_elected:
                custom_instructions = (
                    "- Provide a **detailed** explanation, covering deductibles, coinsurance, "
                    "out-of-pocket maximums, networks, etc., with examples where helpful."
                )
            else:
                custom_instructions = (
                    "- Provide a **short, crisp** summary in 2–3 sentences."
                )

            cfg = build_prompt(condition, desc, custom_instructions)
            # inject the KB ID
            cfg['retrieveAndGenerateConfiguration']['knowledgeBaseConfiguration'][
                'knowledgeBaseId'
            ] = kb_id

            log.info("Calling Bedrock for option '%s' (elected=%s)", desc, is_elected)
            resp = client_bedrock.retrieve_and_generate(**cfg)

            text = resp['output']['text']
            # gather citations if any
            citations = []
            for cit in resp.get('citations', []):
                refs = cit.get('retrievedReferences', [])
                if not refs:
                    continue
                ref = refs[0]
                citations.append({
                    'source': ref['location']['s3Location']['uri'],
                    'text':   ref['content']['text']
                })

            results.append({
                'optionDescription': desc,
                'elected': is_elected,
                'answer': text,
                'citations': citations
            })

        # 5. Return aggregated response
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json; charset=utf-8',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({'results': results}, indent=2)
        }

    except Exception as e:
        log.exception("Fallback Lambda failed")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
