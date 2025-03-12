import json
import boto3

# 1. Import boto3 and create client connection with bedrock
client_bedrock = boto3.client('bedrock-runtime')

def lambda_handler(event, context):
    # 2 a. Store the input in a variable, b. print the event
    input_prompt = event['prompt']
    print(input_prompt)
   
    # 3. Create Request Syntax - Get details from console & body should be json object - use json.dumps for body
    client_bedrockrequest = client_bedrock.invoke_model(
        contentType='application/json',
        accept='application/json',
        modelId='arn:aws:bedrock:us-east-1:653858776174:inference-profile/us.anthropic.claude-3-5-sonnet-20240620-v1:0',
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 200,
            "top_k": 250,
            "stop_sequences": [],
            "temperature": 0.9,
            "top_p": 0.999,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": input_prompt
                        }
                    ]
                }
            ]
        })
    )
    
    # 4. Convert Streaming Body to Byte(.read method) and then Byte to String using json.loads
    client_bedrock_byte = client_bedrockrequest['body'].read()
    
    # 5 a. Print the event and type, b. Store the input in a variable
    client_bedrock_string = json.loads(client_bedrock_byte)
    # print(client_bedrock_string)
    
    # 6. Update the 'return' by changing the 'body'
    client_final_response = client_bedrock_string['content'][0]['text']
    print(client_final_response)

    return {
        'statusCode': 200,
        'body': json.dumps(client_final_response)
    }
