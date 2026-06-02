from typing import TypedDict, List, Annotated
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class GraphState(TypedDict):
    messages : Annotated[list[BaseMessage],add_messages] #Conversation History
    router : str #For the router agent - 1 : general, 2 : jio-faq
    question:str #Question asked by user
    context :str #Retreived context from neo4j
    answer:str #Final Answer that the LLM generates

