
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
            margin:0;
        }
        #message-input:focus{
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
        .message-bubble ol, .message-bubble ul {
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
        .suggested_messagep{
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
        <div id="chat-history">
            <!-- Question Tiles will be dynamically added here -->
        </div>
        <div class="typing-indicator" id="typing-indicator">Bot is typing...</div>
    </div>
    
    <div class="error-message" id="error-message"></div>
    <div id="input-container">
        <input type="text" id="message-input" placeholder="Ask your question" onkeypress="handleEnterKey(event)">
        <button id="send-button" onclick="sendMessage()">
            <svg width="40px" height="40px" viewBox="0 0 24 24" fill="none"><path d="M7.75778 6.14799C6.84443 5.77187 6.0833 5.45843 5.49196 5.30702C4.91915 5.16036 4.18085 5.07761 3.63766 5.62862C3.09447 6.17962 3.18776 6.91666 3.34259 7.48732C3.50242 8.07644 3.8267 8.83302 4.21583 9.7409L4.86259 11.25H10C10.4142 11.25 10.75 11.5858 10.75 12C10.75 12.4142 10.4142 12.75 10 12.75H4.8626L4.21583 14.2591C3.8267 15.167 3.50242 15.9236 3.34259 16.5127C3.18776 17.0833 3.09447 17.8204 3.63766 18.3714C4.18085 18.9224 4.91915 18.8396 5.49196 18.693C6.0833 18.5416 6.84443 18.2281 7.75777 17.852L19.1997 13.1406C19.4053 13.0561 19.6279 12.9645 19.7941 12.867C19.944 12.779 20.3434 12.5192 20.3434 12C20.3434 11.4808 19.944 11.221 19.7941 11.133C19.6279 11.0355 19.4053 10.9439 19.1997 10.8594L7.75778 6.14799Z" fill="#000000"/></svg>
        </button>
    </div>

    <script>
        const userHistory = JSON.parse(sessionStorage.getItem('userHistory')) || [];
        const messageRegistry = { suggested: new Set(), questions: new Set() };
        const API_URL = 'https://0ho0tvkvph.execute-api.us-east-1.amazonaws.com/Dev/chat';
        const chatHistory = document.getElementById('chat-history');
        const messageInput = document.getElementById('message-input');
        const typingIndicator = document.getElementById('typing-indicator');
        const errorMessage = document.getElementById('error-message');

        window.addEventListener('message', function(event) {
            const { questions, suggested_message } = event.data;
            const cleanSuggested = suggested_message.trim();
            const cleanQuestions = questions.map(q => q.trim());

            if (cleanSuggested && !messageRegistry.suggested.has(cleanSuggested)) {
                const suggestedDiv = document.createElement('div');
                suggestedDiv.className = 'suggested_messagep';
                suggestedDiv.textContent = cleanSuggested;
                chatHistory.appendChild(suggestedDiv);
                messageRegistry.suggested.add(cleanSuggested);
            }

            cleanQuestions.forEach(question => {
                if (!messageRegistry.questions.has(question)) {
                    const questionTile = document.createElement('div');
                    questionTile.className = 'question-tile';
                    questionTile.textContent = question;
                    questionTile.onclick = () => sendQuestion(question);
                    chatHistory.appendChild(questionTile);
                    messageRegistry.questions.add(question);
                }
            });

            chatHistory.scrollTop = chatHistory.scrollHeight;
        });

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
            if (isUser) bubble.textContent = message;
            else typeWordByWord(message, bubble);
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
                // Append the required text to the user input
                const modifiedMessage = message + ' column-wise' + ' 1651';
                const response = await fetch(API_URL, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ prompt: modifiedMessage })
                });

                if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
                const data = await response.json();
                appendMessage(data.message, false);

                userHistory.push({ question: message, response: data.message });
                sessionStorage.setItem('userHistory', JSON.stringify(userHistory));
            } catch (error) {
                errorMessage.textContent = `Error: ${error.message}`;
            } finally {
                typingIndicator.style.display = 'none';
            }
        }

        function sendQuestion(question) {
            messageInput.value = question;
            sendMessage();
        }

        function typeWordByWord(response, element) {
            const words = response.split(' ');
            let delay = 0;
            words.forEach((word) => {
                setTimeout(() => { element.innerHTML += word + ' '; }, delay);
                delay += 50;
            });
        }
    </script>
</body>
</html>
