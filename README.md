import { Readable } from 'stream';
import crypto from 'crypto';
import {
  BedrockAgentRuntimeClient,
  InvokeAgentCommand
} from '@aws-sdk/client-bedrock-agent-runtime';

// ✅ No need for NPM install of streamifyResponse — it's injected by Lambda
export const handler = awslambda.streamifyResponse(
  async (event, responseStream) => {
    let body = {};
    try {
      body = JSON.parse(event.body || '{}');
    } catch (e) {
      console.error('Invalid JSON body:', e);
    }

    const userInput = body.message || body.prompt || '';
    const sessionId = body.sessionId || crypto.randomUUID();
    const filterKey = body.filter?.key || 'type';
    const filterValue = body.filter?.value || 'comprehensive';

    const client = new BedrockAgentRuntimeClient({ region: 'us-east-1' });

    const command = new InvokeAgentCommand({
      agentId: 'YOUR_AGENT_ID',
      agentAliasId: 'YOUR_AGENT_ALIAS_ID',
      sessionId: sessionId,
      inputText: userInput,
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
                    key: filterKey,
                    value: filterValue
                  }
                }
              }
            }
          }
        ]
      }
    });

    const result = await client.send(command);

    responseStream.setHeader('Content-Type', 'text/plain; charset=utf-8');
    responseStream.setHeader('Access-Control-Allow-Origin', '*');
    responseStream.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
    responseStream.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    const readable = Readable.from((async function* () {
      for await (const chunk of result.completion || []) {
        if (chunk.chunk?.bytes) {
          yield chunk.chunk.bytes;
        }
      }
    })());

    return readable.pipe(responseStream);
  }
);
