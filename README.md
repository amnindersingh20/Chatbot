import { streamifyResponse } from 'aws-lambda-stream';
import pkg from '@aws-sdk/client-bedrock-agent-runtime';
const { BedrockAgentRuntimeClient, InvokeAgentWithResponseStreamCommand } = pkg;
import crypto from 'crypto';

export const handler = streamifyResponse(async (event, responseStream) => {
  const { message, filter } = JSON.parse(event.body || '{}');
  const sessionId = crypto.randomUUID();

  const client = new BedrockAgentRuntimeClient({ region: 'us-east-1' });

  const command = new InvokeAgentWithResponseStreamCommand({
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
    const response = await client.send(command);
    if (response.completion) {
      for await (const chunk of response.completion) {
        if (chunk.chunk?.bytes) {
          const chunkData = Buffer.from(chunk.chunk.bytes).toString('utf-8');
          responseStream.write(chunkData);
        }
      }
    }
    responseStream.end();
  } catch (error) {
    responseStream.write(`Error: ${error.message}`);
    responseStream.end();
  }
});
