{
  "errorType": "Runtime.UserCodeSyntaxError",
  "errorMessage": "SyntaxError: Named export 'InvokeAgentWithResponseStreamCommand' not found. The requested module '@aws-sdk/client-bedrock-agent-runtime' is a CommonJS module, which may not support all module.exports as named exports.\nCommonJS modules can always be imported via the default export, for example using:\n\nimport pkg from '@aws-sdk/client-bedrock-agent-runtime';\nconst { BedrockAgentRuntimeClient, InvokeAgentWithResponseStreamCommand } = pkg;\n",
  "trace": [
    "Runtime.UserCodeSyntaxError: SyntaxError: Named export 'InvokeAgentWithResponseStreamCommand' not found. The requested module '@aws-sdk/client-bedrock-agent-runtime' is a CommonJS module, which may not support all module.exports as named exports.",
    "CommonJS modules can always be imported via the default export, for example using:",
    "",
    "import pkg from '@aws-sdk/client-bedrock-agent-runtime';",
    "const { BedrockAgentRuntimeClient, InvokeAgentWithResponseStreamCommand } = pkg;",
    "",
    "    at _loadUserApp (file:///var/runtime/index.mjs:1084:17)",
    "    at async UserFunction.js.module.exports.load (file:///var/runtime/index.mjs:1119:21)",
    "    at async start (file:///var/runtime/index.mjs:1282:23)",
    "    at async file:///var/runtime/index.mjs:1288:1"
  ]
}
