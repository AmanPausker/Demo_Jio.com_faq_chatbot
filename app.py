from langgraph.graph import StateGraph, START, END
from agent_state import GraphState
from nodes import retrieve_node, generate_node, general_generation_node

workflow = StateGraph(GraphState)

workflow.add_node("retrieve", retrieve_node)
workflow.add_node("generate", generate_node)
workflow.add_node("general_generation", general_generation_node)

def route_request(state: GraphState):
    router_value = str(state.get("router", "2")).strip()
    if "1" in router_value:
        return "general_generation"
    else:
        return "generate"

workflow.add_edge(START, 'retrieve')
workflow.add_conditional_edges("retrieve", route_request, {
    "general_generation": "general_generation",
    "generate": "generate"
})

workflow.add_edge('generate', END)
workflow.add_edge('general_generation', END)
