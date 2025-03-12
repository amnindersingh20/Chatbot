import json
import boto3
from langchain.chains import LLMChain
from langchain.llms.bedrock import Bedrock
from langchain.prompts import PromptTemplate

bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')

def lambda_handler(event, context):
    try:
        body = json.loads(event['body'])
        prompt = body['prompt']
        llm = Bedrock(client=bedrock, model_id="anthropic.claude-v2")
        response = llm(prompt)
        
        return {
            'statusCode': 200,
            'body': json.dumps({'response': response})
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
