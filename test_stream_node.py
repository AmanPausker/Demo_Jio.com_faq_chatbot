import asyncio
from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated
import operator
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_ollama import ChatOllama

class State(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]

async def node1(state: State):
    client = ChatOllama(model="cow/gemma2_tools:2b", base_url="http://localhost:11434", think=False, streaming=True)
    response = None
    async for chunk in client.astream(state["messages"]):
        if response is None:
            response = chunk
        else:
            response += chunk
    return {"messages": [response]}

workflow = StateGraph(State)
workflow.add_node("node1", node1)
workflow.add_edge(START, "node1")
workflow.add_edge("node1", END)
app = workflow.compile()

async def main():
    state = {"messages": [HumanMessage(content="Say hi")]}
    async for event in app.astream_events(state, version="v2"):
        if event["event"] == "on_chat_model_stream":
            print("STREAM:", event["data"]["chunk"].content)
        elif event["event"] == "on_chat_model_end":
            print("END CHAT MODEL")

asyncio.run(main())
