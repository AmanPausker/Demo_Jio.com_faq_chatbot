from agent_state import GraphState
from nodes import retrieve_node

state = {"question": "what is the weather in mumbai?", "messages": [], "context": "", "answer": "", "router": "2"}
res = retrieve_node(state)
print("CONTEXT:")
print(res["context"])
