import asyncio
from langgraph.graph import StateGraph
from app import workflow
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
import json
from langchain_core.messages import AIMessageChunk

async def test_stream():
    initial_state = {
        "question": "What is JioPlus?",
        "messages": [("user", "What is JioPlus?")],
        "context": "",
        "answer": "",
        "user_id": "test_user",
        "token": "test_token"
    }
    config = {"configurable": {"thread_id": "test_thread"}}
    
    async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as memory:
        langgraph_app = workflow.compile(checkpointer=memory)
        
        async for event in langgraph_app.astream_events(initial_state, config=config, version="v2"):
            kind = event["event"]
            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if isinstance(chunk, AIMessageChunk) and chunk.content:
                    print(f"TOKEN: {chunk.content}")
            elif kind == "on_chat_model_end":
                print(f"END: {event['name']}")

if __name__ == "__main__":
    asyncio.run(test_stream())
