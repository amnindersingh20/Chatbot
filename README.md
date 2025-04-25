import { Readable } from 'stream';
import { BedrockAgentRuntimeClient, InvokeAgentCommand } from '@aws-sdk/client-bedrock-agent-runtime';
import crypto from 'crypto';

export const handler = async (event, context) => {
  const { message, filter } = JSON.parse(event.body || '{}');
  const sessionId = crypto.randomUUID();
  
  // Setup Bedrock client
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
    // Send command to Bedrock
    const result = await client.send(command);

    const responseStream = new Readable({
      read() {
        // Stream response in chunks
        const completion = result?.completion || [];
        
        for (const chunk of completion) {
          if (chunk?.chunk?.bytes) {
            this.push(Buffer.from(chunk.chunk.bytes));  // Push bytes to stream
          }
        }
        this.push(null);  // End of stream
      }
    });

    // Return stream to API Gateway
    return {
      statusCode: 200,
      headers: { 'Content-Type': 'application/json' },
      body: responseStream // Return the stream
    };
    
  } catch (err) {
    console.error(err);
    return {
      statusCode: 500,
      body: JSON.stringify({ error: 'Internal Server Error' })
    };
  }
};
