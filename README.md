2025-04-25T14:07:36.608Z	5790087c-1e08-4a7d-ba6d-0c8ec92c1572	ERROR	ValidationException: Either of inputText or invocationResult with invocationId must be non-empty
    at de_ValidationExceptionRes (/var/task/node_modules/@aws-sdk/client-bedrock-agent-runtime/dist-cjs/index.js:3192:21)
    at de_CommandError (/var/task/node_modules/@aws-sdk/client-bedrock-agent-runtime/dist-cjs/index.js:3045:19)
    at process.processTicksAndRejections (node:internal/process/task_queues:95:5)
    at async /var/task/node_modules/@smithy/middleware-serde/dist-cjs/index.js:35:20
    at async /var/task/node_modules/@smithy/core/dist-cjs/index.js:167:18
    at async /var/task/node_modules/@smithy/middleware-retry/dist-cjs/index.js:320:38
    at async /var/task/node_modules/@aws-sdk/middleware-logger/dist-cjs/index.js:33:22
    at async Runtime.handler (file:///var/task/index.mjs:40:20) {
  '$fault': 'client',
  '$metadata': {
    httpStatusCode: 400,
    requestId: '72b0d229-ab5d-4b03-8a6e-bae88ec6dcc3',
    extendedRequestId: undefined,
    cfId: undefined,
    attempts: 1,
    totalRetryDelay: 0
  }
}
