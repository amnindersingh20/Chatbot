import os
import time
import logging
import boto3
from datetime import datetime, timezone
from langchain_aws import ChatBedrock
from langchain_aws.retrievers import AmazonKnowledgeBasesRetriever
from langchain.chains import ConversationalRetrievalChain
from langchain.schema import ChatMessage
from langchain_core.runnables.history import RunnableWithMessageHistory

CYAN = '\033[96m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
RESET = '\033[0m'

os.environ.setdefault("AWS_PROFILE", "Amnder-2")

os.environ.setdefault("AWS_REGION", "us-east-1")

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

class DynamoDBChatHistory:
    def __init__(self, table_name: str, session_id: str, client=None, region="us-east-1"):
        self.table_name = table_name
        self.session_id = session_id
        self.dynamo = client or boto3.client("dynamodb", region_name=region)

    def add_message(self, message: ChatMessage):
        timestamp = int(time.time() * 1000)
        created_at = datetime.now(timezone.utc).isoformat()
        self.dynamo.put_item(
            TableName=self.table_name,
            Item={
                "SessionId": {"S": self.session_id},
                "Timestamp": {"N": str(timestamp)},
                "CreatedAt": {"S": created_at},
                "MessageType": {"S": message.role},
                "Content": {"S": message.content},
            }
        )

    def clear(self):
        resp = self.dynamo.query(
            TableName=self.table_name,
            KeyConditionExpression="SessionId = :sid",
            ExpressionAttributeValues={":sid": {"S": self.session_id}},
            ProjectionExpression="SessionId, Timestamp"
        )
        with self.dynamo.batch_writer(TableName=self.table_name) as batch:
            for item in resp.get("Items", []):
                batch.delete_item(
                    Key={
                        "SessionId": item["SessionId"],
                        "Timestamp": item["Timestamp"]
                    }
                )

    @property
    def messages(self):
        resp = self.dynamo.query(
            TableName=self.table_name,
            KeyConditionExpression="SessionId = :sid",
            ExpressionAttributeValues={":sid": {"S": self.session_id}},
            ScanIndexForward=True
        )
        msgs = []
        for item in resp.get("Items", []):
            msgs.append(
                ChatMessage(
                    role=item["MessageType"]["S"],
                    content=item["Content"]["S"]
                )
            )
        return msgs

session = boto3.Session(profile_name="Amder-2", region_name="us-east-1")

llm = ChatBedrock(
    model_id="anthropic.claude-3-5-sonnet-2020-v1:0",
    region_name="us-east-1",
    client=session.client("bedrock-runtime", region_name="us-east-1")
)

retriever = AmazonKnowledgeBasesRetriever(
    knowledge_base_id="TGMNY",
    retrieval_config={
        "vectorSearchConfiguration": {
            "numberOfResults": 10,
            "overrideSearchType": "HYBRID"
        }
    },
    client=session.client("bedrock-agent-runtime", region_name="us-east-1")
)

qa_chain = ConversationalRetrievalChain.from_llm(
    llm=llm,
    retriever=retriever,
    output_key="answer",
    return_source_documents=True,
    verbose=False
)


def run_chat(table_name: str, session_id: str):
    logger.info("Starting chat session %s", session_id)
    print(YELLOW + "Type 'reset' to clear history, 'exit' to quit." + RESET)
    history = DynamoDBChatHistory(table_name, session_id)
    while True:
        user_input = input(YELLOW + "You: " + RESET).strip()
        if user_input.lower() in {"exit", "quit"}:
            print(YELLOW + "Goodbye!" + RESET)
            break
        if user_input.lower() == "reset":
            history.clear()
            print(YELLOW + "History cleared." + RESET)
            continue

        history.add_message(ChatMessage(role="user", content=user_input))

        runnable = RunnableWithMessageHistory(
            qa_chain,
            lambda _: history,
            input_messages_key="question",
            history_messages_key="chat_history"
        )
        result = runnable.invoke(
            {"question": user_input},
            config={"configurable": {"session_id": session_id}}
        )

        answer = result.get("answer", "")
        source_docs = result.get("source_documents", [])
        docs_count = len(source_docs)

        print("\n" + "="*60)
        print(CYAN + f"Current Question: {user_input}" + RESET)
        print(GREEN + f"Current Answer: {answer}" + RESET)
        print("="*60 + "\n")

        if docs_count > 0:
            logger.info("Answer retrieved from KB: used %d document(s)", docs_count)
        else:
            logger.info("Answer provided from chat history (no new docs retrieved)")

        history.add_message(ChatMessage(role="assistant", content=answer))

        print(YELLOW + f"(Retrieved {docs_count} document(s) for this response)" + RESET)

        print(YELLOW + "---- Conversation History ----" + RESET)
        for item in history.messages:
            role_label = "You" if item.role == "user" else "Assistant"
            color = CYAN if item.role == "user" else GREEN
            print(color + f"{role_label}: {item.content}" + RESET)
        print(YELLOW + "-"*20 + RESET)


if __name__ == "__main__":
    TABLE_NAME = "POC-Chsion"
    SESSION_ID = input("Enter session ID: ")
    run_chat(TABLE_NAME, SESSION_ID)
