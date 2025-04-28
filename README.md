import { BedrockAgentRuntimeClient, InvokeAgentCommand } from "@aws-sdk/client-bedrock-agent-runtime";
import { BedrockRuntimeClient, InvokeModelWithResponseStreamCommand } from "@aws-sdk/client-bedrock-runtime";
import { StreamingTextResponse } from 'node-stream-api';

const bedrockAgentClient = new BedrockAgentRuntimeClient({ region: "us-east-1" });
const bedrockRuntimeClient = new BedrockRuntimeClient({ region: "us-east-1" });

export const handler = async (event) => {
    const prompt = JSON.parse(event.body).prompt;
    
    // Retrieve relevant context from Knowledge Base
    const agentResponse = await bedrockAgentClient.send(new InvokeAgentCommand({
        agentId: process.env.AGENT_ID,
        agentAliasId: process.env.AGENT_ALIAS_ID,
        sessionId: event.requestContext.requestId,
        inputText: prompt
    }));
    
    // Get the retrieved context from the Knowledge Base
    const context = agentResponse.completion.map(c => c.text).join('\n');

    // Create the final prompt with context
    const fullPrompt = `Context: ${context}\n\nQuestion: ${prompt}\n\nAnswer:`;

    // Invoke the Bedrock model with response streaming
    const command = new InvokeModelWithResponseStreamCommand({
        modelId: "anthropic.claude-v2",
        contentType: "application/json",
        accept: "application/json",
        body: JSON.stringify({
            prompt: fullPrompt,
            max_tokens_to_sample: 3000,
            temperature: 0.5,
        })
    });

    const response = await bedrockRuntimeClient.send(command);
    
    // Create a ReadableStream from the Bedrock response
    const stream = new ReadableStream({
        async start(controller) {
            try {
                for await (const chunk of response.body) {
                    const bytes = new TextDecoder().decode(chunk.chunk.bytes);
                    const data = JSON.parse(bytes);
                    controller.enqueue(data.completion);
                }
                controller.close();
            } catch (error) {
                controller.error(error);
            }
        }
    });

    return {
        statusCode: 200,
        headers: {
            'Content-Type': 'text/plain',
            'Transfer-Encoding': 'chunked'
        },
        body: stream
    };
};
