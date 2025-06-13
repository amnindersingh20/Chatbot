import json
import os
import boto3
import logging

log = logging.getLogger()
log.setLevel(logging.INFO)

client_bedrock = boto3.client('bedrock-agent-runtime', region_name='us-east-1')

POPULATION_KB_MAP = {
    "ATMGMT": "RIBHZRVAQA",
    "BTMGMT": "TGZMV97MNY"
}

# Prompt template with placeholders for dynamic injection
BATCH_RNG_TEMPLATE = """
You are a question answering agent. I will provide you with a set of search results
and a list of benefit plan options. The user has a question about one data point.
Your job is to:
  - Use only the retrieval results to answer the question.
  - Cover the current year and next year data.
  - If you can’t find an exact answer, say you couldn’t find it.
  - For the *elected* option, give a detailed explanation (deductibles, coinsurance, OOP max, etc.).
  - For *other* options, give a 2–3 sentence summary.
Do **not** mention plan IDs—use only their human descriptions.

Search results:
$search_results$

Options:
$option_list$

Question:
What is the {condition} for each of these options?

Answer format instructions:
$output_format_instructions$
"""

# Define a reusable instructions block
OUTPUT_FORMAT_INSTRUCTIONS = (
    "- For the elected option, include detailed deductibles, coinsurance, OOP max, etc.\n"
    "- For other options, give a 2–3 sentence summary.\n"
    "- If you can’t find it in the retrieval results, say \"I couldn’t find that.\""
)

# Read max tokens from environment or default
DEFAULT_MAX_TOKENS = int(os.getenv('MAX_TOKENS', '1024'))


def lambda_handler(event, context):
    try:
        raw_body = event.get('body', {})
        body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body

        # Extract parameters
        params = {p['name']: p['value'] for p in body.get('parameters', [])}
        condition = params.get('condition', '').strip()
        population_type = params.get('populationType', '')
        available_options = body.get('availableOptions', [])
        elected_option = body.get('electedOption', {})

        # Validate
        if not condition or not available_options:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing condition or availableOptions'})
            }

        # KB lookup
        kb_id = POPULATION_KB_MAP.get(population_type, POPULATION_KB_MAP.get('DEFAULT', 'RIBAQA'))

        # Build options list
        lines = []
        for opt in available_options:
            desc = opt.get('optionDescription', '')
            tag = '[ELECTED] ' if elected_option and opt.get('optionId') == elected_option.get('optionId') else ''
            lines.append(f"* {tag}{desc}")
        option_list_block = "\n".join(lines)

        # Final prompt (leave $search_results$ for injection)
        final_prompt = (
            BATCH_RNG_TEMPLATE
            .replace('{condition}', condition)
            .replace('$option_list$', option_list_block)
            .replace('$output_format_instructions$', OUTPUT_FORMAT_INSTRUCTIONS)
        )

        # Bedrock call with inferenceConfig for maxTokens
        response = client_bedrock.retrieve_and_generate(
            input={'text': condition},
            retrieveAndGenerateConfiguration={
                'type': 'KNOWLEDGE_BASE',
                'knowledgeBaseConfiguration': {
                    'knowledgeBaseId': kb_id,
                    'modelArn': (
                        'arn:aws:bedrock:us-east-1:653858776174:'
                        'inference-profile/us.anthropic.claude-3-5-sonnet-20240620-v1:0'
                    ),
                    'retrievalConfiguration': {
                        'vectorSearchConfiguration': {
                            'overrideSearchType': 'HYBRID',
                            'numberOfResults': 20
                        }
                    },
                    'generationConfiguration': {
                        'promptTemplate': {
                            'textPromptTemplate': final_prompt
                        },
                        'inferenceConfig': {
                            'maxTokens': DEFAULT_MAX_TOKENS
                        }
                    }
                }
            }
        )

        # Extract
        answer = response['output']['text']
        citations = []
        for cit in response.get('citations', []):
            refs = cit.get('retrievedReferences', [])
            if not refs:
                continue
            ref = refs[0]
            citations.append({
                'source': ref['location']['s3Location']['uri'],
                'text': ref['content']['text']
            })

        # Return
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json; charset=utf-8','Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'message': answer,'citations': citations}, indent=2)
        }

    except Exception as e:
        log.exception("Bedrock retrieve_and_generate failed")
        return {'statusCode': 500,'body': json.dumps({'error': str(e)})}
