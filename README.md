2025-04-25T12:08:11.278Z	undefined	ERROR	Uncaught Exception 	{
    "errorType": "TypeError",
    "errorMessage": "awslambda.streamifyResponse is not a function",
    "stack": [
        "TypeError: awslambda.streamifyResponse is not a function",
        "    at file:///var/task/index.mjs:13:34",
        "    at ModuleJob.run (node:internal/modules/esm/module_job:271:25)",
        "    at async onImport.tracePromise.__proto__ (node:internal/modules/esm/loader:578:26)",
        "    at async _tryAwaitImport (file:///var/runtime/index.mjs:1008:16)",
        "    at async _tryRequire (file:///var/runtime/index.mjs:1057:86)",
        "    at async _loadUserApp (file:///var/runtime/index.mjs:1081:16)",
        "    at async UserFunction.js.module.exports.load (file:///var/runtime/index.mjs:1119:21)",
        "    at async start (file:///var/runtime/index.mjs:1282:23)",
        "    at async file:///var/runtime/index.mjs:1288:1"
    ]
}
