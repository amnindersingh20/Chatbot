// index.mjs
import { pipeline } from 'stream/promises';
import { Readable } from 'stream';
import * as awslambda from 'aws-lambda';
import {
  BedrockAgentRuntimeClient,
  InvokeAgentCommand
} from '@aws-sdk/client-bedrock-agent-runtime';

// 1️⃣ Initialize the Bedrock client
const client = new BedrockAgentRuntimeClient({ region: 'us-east-1' });

export const handler = awslambda.streamifyResponse(
  async (event, responseStream) => {
    // 2️⃣ Parse incoming JSON
    const {
      message,
      prompt,
      sessionId: sid,
      filter = {}
    } = JSON.parse(event.body || '{}');
    const inputText = message || prompt || '';
    const sessionId = sid || event.requestContext.requestId;
    const { key = 'type', value = 'comprehensive' } = filter;

    // 3️⃣ Call Bedrock Agent with your KB + dynamic filter
    const resp = await client.send(new InvokeAgentCommand({
      agentId:      'YOUR_AGENT_ID',        // ← replace
      agentAliasId: 'YOUR_AGENT_ALIAS_ID',  // ← replace
      sessionId,
      inputText,
      sessionState: {
        knowledgeBaseConfigurations: [
          {
            knowledgeBaseId: 'YOUR_KB_ID',   // ← replace
            retrievalConfiguration: {
              vectorSearchConfiguration: {
                overrideSearchType: 'HYBRID',
                numberOfResults:    10,
                filter: {
                  equals: { key, value }
                }
              }
            }
          }
        ]
      }
    }));

    // 4️⃣ Prepare the HTTP response for streaming + CORS
    responseStream.setContentType('text/plain; charset=utf-8');
    responseStream.setHeader('Access-Control-Allow-Origin', '*');
    responseStream.setHeader('Access-Control-Allow-Headers', 'Content-Type');
    responseStream.setHeader('Access-Control-Allow-Methods', 'POST,OPTIONS');

    // 5️⃣ Convert the async iterator into a Readable and pipe it out
    const readStream = Readable.from(
      (async function* () {
        for await (const ev of resp.completion || []) {
          if (ev.chunk?.bytes) yield ev.chunk.bytes;
        }
      })()
    );
    await pipeline(readStream, responseStream);
  }
);
