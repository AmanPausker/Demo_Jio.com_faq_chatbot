from typing import TypedDict, List
from langchain_core.messages import BaseMessage

class GraphState(TypedDict):
    messages : List[BaseMessage] #Conversation History
    router : int #For the router agent - 1 : general, 2 : jio-faq
    question:str #Question asked by user
    context :str #Retreived context from neo4j
    answer:str #Final Answer that the LLM generates

