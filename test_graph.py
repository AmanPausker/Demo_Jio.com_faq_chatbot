import asyncio
from app import workflow
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

async def main():
    async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as memory:
        app = workflow.compile(checkpointer=memory)
        config = {"configurable": {"thread_id": "test_user_123"}}
        
        # Test 1: "Whats the weather today?" (Should ask for location)
        state1 = {
            "question": "Whats the weather today?",
            "messages": [("user", "Whats the weather today?")],
            "context": "",
            "user_id": "test",
            "token": ""
        }
        res1 = await app.ainvoke(state1, config=config)
        print("TEST 1 ANSWER:", res1["answer"])
        
        # Test 2: "What is the weather in goa?" (Should trigger tool)
        state2 = {
            "question": "What is the weather in goa?",
            "messages": [("user", "What is the weather in goa?")],
            "context": "",
            "user_id": "test",
            "token": ""
        }
        res2 = await app.ainvoke(state2, config=config)
        print("TEST 2 ANSWER:", res2["answer"])

asyncio.run(main())
