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
    #loading {
      font-size: 1.2rem;
      color: gray;
      font-style: italic;
    }
  </style>
</head>
<body>
  <h2>Stream Lambda Response</h2>
  <input type="text" id="prompt" placeholder="Enter prompt..." style="width: 60%;" />
  <button onclick="startStream()">Send</button>
  
  <div id="loading" style="display: none;">Streaming...</div>
  <div id="output"></div>

  <script>
    async function startStream() {
      const prompt = document.getElementById('prompt').value;
      const output = document.getElementById('output');
      const loading = document.getElementById('loading');
      output.textContent = '';
      loading.style.display = 'block';

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
        loading.style.display = 'none';
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let done = false;
      let result = '';
      
      while (!done) {
        const { done: isDone, value } = await reader.read();
        done = isDone;
        result += decoder.decode(value, { stream: true });
        
        output.textContent = result; // Display progressively
      }

      loading.style.display = 'none';  // Hide loading when done
    }
  </script>
</body>
</html>
