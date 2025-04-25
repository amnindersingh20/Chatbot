<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Lambda Streaming Test</title>
  <style>
    body {
      font-family: sans-serif;
      margin: 2rem;
    }
    #output {
      white-space: pre-wrap;
      border: 1px solid #ccc;
      padding: 1rem;
      margin-top: 1rem;
      height: 200px;
      overflow-y: auto;
      background: #f9f9f9;
    }
  </style>
</head>
<body>
  <h2>Stream Lambda Response</h2>
  <input type="text" id="prompt" placeholder="Enter prompt..." style="width: 60%;" />
  <button onclick="startStream()">Send</button>
  
  <div id="output"></div>

  <script>
    async function startStream() {
      const prompt = document.getElementById('prompt').value;
      const output = document.getElementById('output');
      output.textContent = 'Streaming...\n';

      const response = await fetch('https://YOUR_FUNCTION_URL_HERE', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          message: prompt,
          filter: { key: "type", value: "comprehensive" }
        })
      });

      if (!response.body) {
        output.textContent = 'No response stream found.';
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        output.textContent += decoder.decode(value, { stream: true });
      }
    }
  </script>
</body>
</html>
