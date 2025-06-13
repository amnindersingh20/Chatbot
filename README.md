import json
import os
import boto3
import logging

log = logging.getLogger()
log.setLevel(logging.INFO)

# It's good practice to initialize the client outside the handler
# to leverage Lambda's execution context reuse.
client_bedrock = boto3.client('bedrock-agent-runtime', region_name='us-east-1')

POPULATION_KB_MAP = {
    "ATMGMT": "RIBHZRVAQA",
    "BTMGMT": "TGZMV97MNY"
    # It's a good practice to have a default fallback KB ID.
    # The original code had a bug here, it should be 'DEFAULT' not POPULATION_KB_MAP.get('DEFAULT', 'RIBAQA')
    # This is now corrected in the logic below.
}
DEFAULT_KB_ID = "RIBAQA" # Define a default KB ID separately

# The core instructions are now part of the main prompt, not a separate template.
# The $search_results$ placeholder is removed because Bedrock will add it automatically.
PROMPT_INSTRUCTIONS = """
You are a question answering agent. I will provide you with a list of benefit plan options and a question.
Your job is to use the retrieved search results to answer the question about the provided options.

Your strict rules are:
 - Use only the retrieval results to answer the question.
 - Cover the current year and next year data if available in the results.
 - If you cannot find an exact answer for an option in the results, you must state: "I couldn't find that."
 - For the option marked with [ELECTED], give a detailed explanation including deductibles, coinsurance, and out-of-pocket maximums.
 - For all other options, provide a brief 2–3 sentence summary.
 - Do not mention plan IDs—use only their human-readable descriptions.
"""

def lambda_handler(event, context):
    try:
        raw_body = event.get('body', {})
        # Ensure body is a dictionary
        body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body

        params = {p['name']: p['value'] for p in body.get('parameters', [])}
        condition = params.get('condition', '').strip()
        population_type = params.get('populationType', '')
        available_options = body.get('availableOptions', [])
        elected_option = body.get('electedOption', {})

        if not condition or not available_options:
            log.warning("Request is missing 'condition' or 'availableOptions'.")
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing condition or availableOptions'})
            }

        # Correctly get the KB ID with a fallback to the default
        kb_id = POPULATION_KB_MAP.get(population_type, DEFAULT_KB_ID)
        log.info(f"Using Knowledge Base ID: {kb_id} for population type: {population_type or 'Default'}")

        # Build the list of options, marking the elected one
        lines = []
        for opt in available_options:
            desc = opt.get('optionDescription', '').strip()
            if desc.lower() == 'no coverage':
                log.info(f"Skipping option '{desc}' due to no coverage")
                continue
            
            # Add [ELECTED] tag for easy identification by the model
            tag = '[ELECTED] ' if elected_option and opt.get('optionId') == elected_option.get('optionId') else ''
            lines.append(f"* {tag}{desc}")

        if not lines:
            log.info("No applicable options to process after filtering.")
            return {
                'statusCode': 200,
                'headers': {'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'message': 'No applicable options to process.', 'citations': []})
            }

        option_list_block = "\n".join(lines)

        # Construct the final, comprehensive prompt for the 'input' field
        # This replaces the old template system.
        final_input_text = f"""
{PROMPT_INSTRUCTIONS}

Here are the benefit plan options:
{option_list_block}

Here is the user's question:
What is the {condition} for each of these options?
"""
        
        log.info(f"Final input text for Bedrock:\n{final_input_text}")

        # Call Bedrock API without the 'generationConfiguration' to enable citations
        response = client_bedrock.retrieve_and_generate(
            input={'text': final_input_text},
            retrieveAndGenerateConfiguration={
                'type': 'KNOWLEDGE_BASE',
                'knowledgeBaseConfiguration': {
                    'knowledgeBaseId': kb_id,
                    'modelArn': (
                        'arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-sonnet-20240229-v1:0'
                    ),
                    'retrievalConfiguration': {
                        'vectorSearchConfiguration': {
                            'overrideSearchType': 'HYBRID',
                            'numberOfResults': 30
                        }
                    },
                    # By OMITTING 'generationConfiguration', we allow Bedrock to use its
                    # default, citation-friendly prompting strategy.
                }
            }
        )

        answer = response['output']['text']
        citations = []
        
        # This citation processing logic is correct and will now work
        # because the 'citations' field should be present in the response.
        for cit in response.get('citations', []):
            retrieved_refs = cit.get('retrievedReferences', [])
            if not retrieved_refs:
                continue
            
            # Each citation can have multiple references, let's capture them all
            for ref in retrieved_refs:
                # Ensure location and content exist to avoid key errors
                if 'location' in ref and 's3Location' in ref['location'] and 'content' in ref:
                    citations.append({
                        'source': ref['location']['s3Location']['uri'],
                        'text': ref['content']['text']
                    })
                else:
                    log.warning(f"Skipping malformed reference: {ref}")

        log.info(f"Successfully generated answer and found {len(citations)} citation references.")

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'message': answer, 'citations': citations}, indent=2)
        }

    except Exception as e:
        log.exception("An error occurred in the lambda_handler")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
