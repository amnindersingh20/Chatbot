import json
import boto3
import logging

log = logging.getLogger()
log.setLevel(logging.INFO)

client_bedrock = boto3.client('bedrock-agent-runtime', region_name='us-east-1')

POPULATION_KB_MAP = {
    "ATMGMT": "RIBHZRVAQA",
    "BTMGMT": "TGZMV97MNY"
}
DEFAULT_KB_ID = "RIBHZRVAQA"

PROMPT_INSTRUCTIONS = """
You are a question-answering agent. You will be given a list of benefit-plan options and a question.
Your job is to use only the provided retrieval results to answer the question about the provided options.

Strict rules:
 - Always pull data for next year’s plans by default—unless the user explicitly asks for current-year details when multiple years are available.
 - If next-year data is not available, fall back to current-year information.
 - If you cannot find an exact answer for a plan feature in the retrievals, state: “I couldn’t find that.”
 - Do not mention plan IDs—use only each plan’s human-readable description.

Answer format:
 - Organize your response into clearly labeled sections (e.g., **In-Network**, **Out-of-Network**, **Option Summaries**, etc.).
 - For every plan option except the one marked **[ELECTED]**, provide a concise 2–3 sentence summary under its own heading.
 - For the **[ELECTED]** option, include a focused breakdown of its **deductible**, **coinsurance**, and **out-of-pocket maximum**.

Targeted follow-ups:
 - If the user’s question calls out a specific option by name, answer only for that option.

Use this structure on every response to keep plan comparisons clean, consistent, and easy to scan.
"""

def lambda_handler(event, context):
    try:
        raw_body = event.get('body', {})
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

        kb_id = POPULATION_KB_MAP.get(population_type, DEFAULT_KB_ID)
        log.info(f"Using Knowledge Base ID: {kb_id} for population type: {population_type or 'Default'}")

        # Separate elected and available lists
        available_list = []
        elected_desc = None

        for opt in available_options:
            desc = opt.get('optionDescription', '').strip()
            if desc.lower() == 'no coverage':
                log.info(f"Skipping option '{desc}' due to no coverage")
                continue

            if elected_option and opt.get('optionId') == elected_option.get('optionId'):
                elected_desc = desc
            else:
                available_list.append(desc)

        if not elected_desc and not available_list:
            log.info("No applicable options to process after filtering.")
            return {
                'statusCode': 200,
                'headers': {'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'message': 'No applicable options to process.', 'citations': []})
            }

        # Build markdown blocks
        blocks = []
        if elected_desc:
            blocks.append(f"**Elected Option:** {elected_desc}")

        if available_list:
            blocks.append("**Available Options:**")
            for desc in available_list:
                blocks.append(f"- {desc}")

        option_list_block = "\n\n".join(blocks)

        # Compose final prompt without leading blank lines
        final_input_text = PROMPT_INSTRUCTIONS.strip() + "\n\n" + \
            "Here are the benefit plan options:\n" + option_list_block + "\n\n" + \
            "Here is the user's question:\n" + f"What is the {condition} for each of these options?"

        log.info(f"Final input text for Bedrock:\n{final_input_text}")

        # Invoke Bedrock with deterministic settings
        response = client_bedrock.retrieve_and_generate(
            input={'text': final_input_text},
            retrieveAndGenerateConfiguration={
                'type': 'KNOWLEDGE_BASE',
                'knowledgeBaseConfiguration': {
                    'knowledgeBaseId': kb_id,
                    'modelArn': (
                        'arn:aws:bedrock:us-east-1::foundation-model/'  
                        'anthropic.claude-3-5-sonnet-20240620-v1:0'
                    ),
                    'retrievalConfiguration': {
                        'vectorSearchConfiguration': {
                            'overrideSearchType': 'HYBRID',
                            'numberOfResults': 60
                        }
                    },
                    'generationConfiguration': {
                        'maxTokens': 1024,
                        'temperature': 0.0,
                        'topP': 1.0
                    }
                }
            }
        )

        # Extract answer and citations
        answer = response['output']['text']
        citations = []
        for cit in response.get('citations', []):
            for ref in cit.get('retrievedReferences', []):
                loc = ref.get('location', {})
                content = ref.get('content', {}).get('text')
                uri = loc.get('s3Location', {}).get('uri')
                if uri and content:
                    citations.append({'source': uri, 'text': content})
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
