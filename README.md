import { streamifyResponse } from '@aws-sdk/streaming-response-handler-node';
import { BedrockAgentRuntimeClient, InvokeAgentWithResponseStreamCommand } from '@aws-sdk/client-bedrock-agent-runtime';
import crypto from 'crypto';

export const handler = streamifyResponse(async (event, responseStream) => {
  // Parse input from API Gateway
  const { message, filter } = JSON.parse(event.body || '{}');
  const sessionId = crypto.randomUUID();

  // Initialize Bedrock client
  const client = new BedrockAgentRuntimeClient({ region: 'us-east-1' });

  // Configure Bedrock streaming command
  const command = new InvokeAgentWithResponseStreamCommand({
    agentId: 'YOUR_AGENT_ID', // Replace with your agent ID
    agentAliasId: 'YOUR_AGENT_ALIAS_ID', // Replace with your alias ID
    sessionId: sessionId,
    inputText: message,
    sessionState: {
      knowledgeBaseConfigurations: [
        {
          knowledgeBaseId: 'YOUR_KB_ID', // Replace with your KB ID
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
    // Get streaming response from Bedrock
    const response = await client.send(command);

    // Stream chunks to client
    if (response.completion) {
      for await (const chunk of response.completion) {
        if (chunk.chunk?.bytes) {
          const chunkData = Buffer.from(chunk.chunk.bytes).toString('utf-8');
          responseStream.write(chunkData); // Send chunk to client
        }
      }
    }

    responseStream.end();

  } catch (error) {
    responseStream.write(`Error: ${error.message}`);
    responseStream.end();
  }
});
