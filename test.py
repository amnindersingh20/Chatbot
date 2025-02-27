import json
import os
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from uvicorn import Config, Server
from sentence_transformers import SentenceTransformer, util
import numpy as np
import boto3
import requests

# S3 Configuration – update these with your actual S3 details
S3_BUCKET_NAME = "your-bucket-name"
S3_OBJECT_KEY = "your-file.json"
AWS_REGION = "your-region"

# Generative model API configuration (example uses OpenAI's Chat API)
OPENAI_API_KEY = "your-openai-api-key"
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

app = FastAPI()

# Global variables for the knowledge base, embeddings, and retrieval model
knowledge_base = []
kb_embeddings = None
retrieval_model = None

@app.on_event("startup")
def load_knowledge():
    global knowledge_base, kb_embeddings, retrieval_model
    try:
        print("Fetching knowledge base from S3 bucket...")
        s3_client = boto3.client("s3", region_name=AWS_REGION)
        response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=S3_OBJECT_KEY)
        data = response["Body"].read().decode("utf-8")
        knowledge_base = json.loads(data)
        print("Knowledge base loaded from S3:", knowledge_base)
    except Exception as e:
        knowledge_base = []
        print("Error loading knowledge base from S3:", e)
    
    try:
        retrieval_model = SentenceTransformer('all-MiniLM-L6-v2')
        print("Retrieval NLP model loaded.")
        questions = [item.get("question", "") for item in knowledge_base]
        if questions:
            kb_embeddings = retrieval_model.encode(questions, convert_to_tensor=True)
            print("Knowledge base embeddings computed.")
        else:
            kb_embeddings = None
            print("No questions found in the knowledge base.")
    except Exception as e:
        print("Error loading retrieval model or computing embeddings:", e)
        kb_embeddings = None

def search_knowledge(query: str, threshold: float = 0.5):
    global kb_embeddings, retrieval_model
    if not knowledge_base or kb_embeddings is None:
        return ""
    query_embedding = retrieval_model.encode(query, convert_to_tensor=True)
    cosine_scores = util.cos_sim(query_embedding, kb_embeddings)[0]
    best_score = float(cosine_scores.max())
    best_idx = int(cosine_scores.argmax())
    print(f"Best similarity score: {best_score}")
    if best_score >= threshold:
        return knowledge_base[best_idx].get("answer", "")
    else:
        return ""

def generate_response(query: str, context: str = "") -> str:
    """
    This function calls the OpenAI Chat API to generate a response.
    It builds a prompt that includes any retrieved context along with the query.
    """
    if context:
        prompt = f"Based on the following context, answer the question in a detailed manner.\n\nContext: {context}\n\nQuestion: {query}\n\nAnswer:"
    else:
        prompt = f"Answer the question: {query}"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}"
    }
    
    data = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7
    }
    
    try:
        response = requests.post(OPENAI_API_URL, headers=headers, json=data)
        response.raise_for_status()
        result = response.json()
        generated_text = result["choices"][0]["message"]["content"].strip()
        return generated_text
    except Exception as e:
        print(f"Error generating response: {e}")
        return "I'm sorry, I couldn't generate an answer at this time."

@app.get("/chat")
def chat(query: str):
    print(f"Received chat request with query: {query}")
    retrieved_context = search_knowledge(query)
    print(f"Retrieved context: {retrieved_context}")
    # Use the generative model to produce a final answer, combining query and retrieved context
    final_answer = generate_response(query, retrieved_context)
    print(f"Returning generated response: {final_answer}")
    return {"response": final_answer}

@app.get("/", response_class=FileResponse)
def get_ui():
    if os.path.exists("frontend.html"):
        return FileResponse("frontend.html")
    else:
        raise HTTPException(status_code=404, detail="Frontend file not found")

if __name__ == "__main__":
    config = Config(app=app, host="0.0.0.0", port=8000, loop="asyncio")
    server = Server(config)
    asyncio.get_event_loop().run_until_complete(server.serve())
