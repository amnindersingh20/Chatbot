import { BedrockAgentRuntimeClient, InvokeAgentCommand } from '@aws-sdk/client-bedrock-agent-runtime';
import crypto from 'crypto';

export const handler = async (event, context) => {
  const { message, filter } = JSON.parse(event.body || '{}');
  const sessionId = crypto.randomUUID();
  
  const client = new BedrockAgentRuntimeClient({ region: 'us-east-1' });

  const command = new InvokeAgentCommand({
    agentId: 'YOUR_AGENT_ID',
    agentAliasId: 'YOUR_AGENT_ALIAS_ID',
    sessionId: sessionId,
    inputText: message,
    sessionState: {
      knowledgeBaseConfigurations: [
        {
          knowledgeBaseId: 'YOUR_KB_ID',
          retrievalConfiguration: {
            vectorSearchConfiguration: {
              overrideSearchType: 'HYBRID',
              numberOfResults: 10,
              filter: {
                equals: {
                  key: filter?.key || 'type',
                  value: filter?.value || 'comprehensive'
                }
              }
            }
          }
        }
      ]
    }
  });

  try {
    const result = await client.send(command);
    let responseBody = '';

    // Process each chunk from the completion
    const completion = result.completion || [];
    for (const chunk of completion) {
      if (chunk?.chunk?.bytes) {
        responseBody += Buffer.from(chunk.chunk.bytes).toString('utf-8');
      }
    }

    return {
      statusCode: 200,
      headers: { 'Content-Type': 'text/plain' }, // Adjust content type if needed
      body: responseBody
    };
    
  } catch (err) {
    console.error(err);
    return {
      statusCode: 500,
      body: JSON.stringify({ error: 'Internal Server Error' })
    };
  }
};
