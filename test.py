import json
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sentence_transformers import SentenceTransformer, util
import numpy as np
import boto3
from transformers import AutoModelForCausalLM, AutoTokenizer
from mangum import Mangum  # For AWS Lambda

# S3 Configuration – update these with your actual S3 details or environment variables
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "your-bucket-name")
S3_OBJECT_KEY = os.environ.get("S3_OBJECT_KEY", "your-file.json")
AWS_REGION = os.environ.get("AWS_REGION", "your-region")

app = FastAPI()

# Add CORS middleware to allow calls from your local frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this to your local dev domain (e.g., http://localhost:3000)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global variables for the knowledge base, embeddings, retrieval model, and generative model
knowledge_base = []
kb_embeddings = None
retrieval_model = None
gen_model = None
gen_tokenizer = None

@app.on_event("startup")
def load_knowledge():
    global knowledge_base, kb_embeddings, retrieval_model, gen_model, gen_tokenizer
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

    try:
        print("Loading generative model (DistilGPT-2)...")
        gen_tokenizer = AutoTokenizer.from_pretrained("distilgpt2")
        gen_model = AutoModelForCausalLM.from_pretrained("distilgpt2")
        print("Generative model loaded.")
    except Exception as e:
        print("Error loading generative model:", e)
        gen_model = None
        gen_tokenizer = None

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
    if context:
        prompt = f"Context: {context}\nQuestion: {query}\nAnswer:"
    else:
        prompt = f"Question: {query}\nAnswer:"
    
    if gen_model is None or gen_tokenizer is None:
        return "I'm sorry, the generative model is not available."
    
    try:
        input_ids = gen_tokenizer.encode(prompt, return_tensors="pt")
        output = gen_model.generate(input_ids, max_length=150, num_return_sequences=1, no_repeat_ngram_size=2)
        generated_text = gen_tokenizer.decode(output[0], skip_special_tokens=True)
        if generated_text.startswith(prompt):
            generated_text = generated_text[len(prompt):].strip()
        return generated_text
    except Exception as e:
        print(f"Error during generation: {e}")
        return "I'm sorry, I couldn't generate an answer at this time."

@app.get("/chat")
def chat(query: str):
    print(f"Received chat request with query: {query}")
    retrieved_context = search_knowledge(query)
    print(f"Retrieved context: {retrieved_context}")
    final_answer = generate_response(query, retrieved_context)
    print(f"Returning generated response: {final_answer}")
    return {"response": final_answer}

# Create a Mangum handler for AWS Lambda
handler = Mangum(app)
