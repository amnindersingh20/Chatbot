<!DOCTYPE html>
<html>

<head>
    <title>AI Enrollment Chatbot</n>
    <style>
        /* ... existing styles unchanged ... */
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
            <!-- send icon -->
        </button>
    </div>

    <script>
        // Retrieve constMsg from sessionStorage
        const constMsg = JSON.parse(sessionStorage.getItem('constMsg') || '{}');
        // Build plan map from optionId to optionDescription
        const optionMap = {};
        if (Array.isArray(constMsg.availableOptions)) {
            constMsg.availableOptions.forEach(opt => {
                optionMap[String(opt.optionId)] = opt.optionDescription;
            });
        }
        // Extract all available optionIds as plans
        const planIds = Object.keys(optionMap);

        const API_URL = 'https://0h.execute-api.us-east-1.amazonaws.com/Dev/chat';
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
            bubble.textContent = message;
            messageDiv.appendChild(bubble);
            chatHistory.appendChild(messageDiv);
            chatHistory.scrollTop = chatHistory.scrollHeight;
        }

        async function sendMessage() {
            const text = messageInput.value.trim();
            if (!text) return;
            messageInput.value = '';
            errorMessage.textContent = '';
            appendMessage(text, true);
            typingIndicator.style.display = 'block';

            // Build parameters array: one condition + one plan per optionId
            const params = [{ name: 'condition', value: text }];
            planIds.forEach(id => params.push({ name: 'plan', value: id }));

            try {
                const response = await fetch(API_URL, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ parameters: params })
                });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);

                let data = await response.json();
                // unwrap nested body if needed
                if (data.body && typeof data.body === 'string') {
                    try { data = JSON.parse(data.body); } catch {};
                }

                let reply = '';
                if (Array.isArray(data)) {
                    reply = data.map(item => {
                        if (item.data) {
                            return item.data.map(d => {
                                const desc = optionMap[String(d.plan)] || d.plan;
                                return `For "${d.condition}" under "${desc}", the value is: ${d.value}`;
                            }).join('\n');
                        }
                        if (item.value) {
                            const desc = optionMap[String(item.plan)] || item.plan;
                            return `For "${text}" under "${desc}", the value is: ${item.value}`;
                        }
                        {
                            const desc = optionMap[String(item.plan)] || item.plan;
                            return `For "${text}" under "${desc}", error: ${item.error}`;
                        }
                    }).join('\n\n');
                } else {
                    reply = JSON.stringify(data);
                }

                appendMessage(reply, false);
            } catch (err) {
                errorMessage.textContent = `Error: ${err.message}`;
            } finally {
                typingIndicator.style.display = 'none';
            }
        }
    </script>
</body>

</html>
