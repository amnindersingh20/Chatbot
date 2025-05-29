<!DOCTYPE html>
<html>

<head>
    <title>AI Enrollment Chatbot</title>
    <style>
        body {
            font-family: 'Segoe UI', Arial, sans-serif;
            margin: 0;
            padding: 0;
            height: 100vh;
            display: flex;
            flex-direction: column;
            background: #fff;
        }

        #chat-container {
            max-width: 800px;
            margin: 0 auto;
            width: 100%;
            padding: 0;
            margin-bottom: 20px;
            box-sizing: border-box;
            display: flex;
            flex-direction: column;
            height: calc(100vh - 120px);
        }

        #chat-history {
            overflow-y: auto;
            padding: 10px;
            background: transparent;
            border-radius: 10px;
            margin-bottom: 25px;
        }

        .message {
            margin-bottom: 15px;
            display: flex;
        }

        .user-message {
            justify-content: flex-end;
        }

        .bot-message {
            justify-content: flex-start;
        }

        .message-bubble {
            max-width: 100%;
            padding: 12px 14px;
            border-radius: 15px;
            word-break: break-word;
            white-space: pre-wrap;
            font-size: 14px;
        }

        .user-message .message-bubble {
            background: #007bff;
            color: white;
            border-bottom-right-radius: 5px;
        }

        .bot-message .message-bubble {
            background: #e9ecef;
            color: #212529;
            border-bottom-left-radius: 5px;
        }

        #input-container {
            display: inline-flex;
            padding: 2%;
            background: #fff;
            position: fixed;
            bottom: 0;
            width: 96%;
            margin: 0;
        }

        #message-input:focus {
            border-color: #007bff;
        }

        #message-input {
            padding: 15px 60px 15px 8px;
            width: 100%;
            border: 2px solid #ababab;
            border-radius: 8px;
            font-size: 14px;
            outline: none;
        }

        #send-button {
            padding: 2px 15px;
            background: transparent;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            position: absolute;
            right: 30px;
            top: 28%;
        }

        .typing-indicator {
            display: none;
            padding: 10px;
            font-style: italic;
            color: #6c757d;
        }

        .error-message {
            color: #dc3545;
            padding: 10px;
            text-align: center;
        }

        .message-bubble ol,
        .message-bubble ul {
            padding-left: 1.5em;
            margin: 8px 0;
        }

        .message-bubble ul li::before {
            content: "â€¢";
            color: #3498db;
            margin-right: 8px;
        }

        .badge {
            background-color: powderblue;
            color: #000;
            padding: 4px 8px;
            text-align: center;
            border-radius: 5px;
            margin: 5px;
            display: inline-block;
        }

        .question-tile {
            background-color: #f0f0f0;
            border: 1px solid #ccc;
            border-radius: 5px;
            padding: 10px;
            font-size: 14px;
            margin: 5px 0;
            cursor: pointer;
            transition: background-color 0.3s, box-shadow 0.3s;
        }

        .suggested_messagep {
            padding: 0;
            margin: 0;
            font-style: italic;
            font-weight: 500;
        }

        .question-tile:hover {
            background-color: #e0e0e0;
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        }

        .question-tile:active {
            background-color: #d0d0d0;
        }
    </style>
</head>

<body>
    <div id="chat-container">
        <div id="chat-history"></div>
        <div class="typing-indicator" id="typing-indicator">Bot is typing...</div>
    </div>

    <div class="error-message" id="error-message"></div>
    <div id="input-container">
        <input type="text" id="message-input" placeholder="Ask your question" onkeypress="handleEnterKey(event)">
        <button id="send-button" onclick="sendMessage()">
            <svg width="40px" height="40px" viewBox="0 0 24 24" fill="none">
                <path
                    d=""
                    fill="#000000" />
            </svg>
        </button>
    </div>

    <script>
        const userHistory = JSON.parse(sessionStorage.getItem('userHistory')) || [];
        const API_URL = 'https://0ho.execute-api.us-east-1.amazonaws.com/Dev/chat';
        const chatHistory = document.getElementById('chat-history');
        const messageInput = document.getElementById('message-input');
        const typingIndicator = document.getElementById('typing-indicator');
        const errorMessage = document.getElementById('error-message');

        function handleEnterKey(event) {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                sendMessage();
            }
        }

        function appendMessage(message, isUser) {
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${isUser ? 'user-message' : 'bot-message'}`;
            const bubble = document.createElement('div');
            bubble.className = 'message-bubble';
            if (isUser) {
                bubble.textContent = message;
            } else {
                typeWordByWord(message, bubble);
            }
            messageDiv.appendChild(bubble);
            chatHistory.appendChild(messageDiv);
            chatHistory.scrollTop = chatHistory.scrollHeight;
        }

        async function sendMessage() {
            const message = messageInput.value.trim();
            if (!message) return;
            messageInput.value = '';
            errorMessage.textContent = '';
            appendMessage(message, true);
            typingIndicator.style.display = 'block';

            try {
                let condition = '';
                let plan = '1651';

                const planRegex = /\bfor\s+plan\s+(\d+)\b/i;
                const match = message.match(planRegex);

                if (match) {
                    plan = match[1];
                    condition = message.replace(planRegex, '').trim();
                } else {
                    condition = message;
                }

                const response = await fetch(API_URL, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        parameters: [
                            { name: 'condition', value: condition },
                            { name: 'plan', value: plan }
                        ]
                    })
                });

                if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
                let data = await response.json();

                // Handle double-encoded response body
                if (data.body && typeof data.body === 'string') {
                    try {
                        const parsedBody = JSON.parse(data.body);
                        Object.assign(data, parsedBody);
                    } catch (e) {
                        console.warn('Failed to parse nested body JSON');
                    }
                }

                let botReply = '';

                if (typeof data === 'string') {
                    botReply = data;
                } else if (Array.isArray(data)) {
                    botReply = data.map(item =>
                        `For "${item.condition}" under plan ${item.plan}, the value is: ${item.value}`
                    ).join('\n\n');
                } else if (typeof data.message === 'string') {
                    botReply = data.message;
                } else if (data.value && data.condition && data.plan) {
                    botReply = `For "${data.condition}" under plan ${data.plan}, the value is: ${data.value}`;
                } else {
                    botReply = '[No meaningful response]';
                }

                appendMessage(botReply, false);
                userHistory.push({ question: message, response: botReply });
                sessionStorage.setItem('userHistory', JSON.stringify(userHistory));

            } catch (error) {
                errorMessage.textContent = `Error: ${error.message}`;
            } finally {
                typingIndicator.style.display = 'none';
            }
        }

        function typeWordByWord(response, element) {
            const words = response.split(' ');
            let delay = 0;
            words.forEach((word) => {
                setTimeout(() => {
                    element.innerHTML += word + ' ';
                }, delay);
                delay += 50;
            });
        }
    </script>
</body>

</html>
