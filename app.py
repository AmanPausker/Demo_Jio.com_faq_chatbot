

import gradio as gr
from langgraph.graph import StateGraph, START, END
from agent_state import GraphState
from nodes import retrieve_node, generate_node

workflow = StateGraph(GraphState)

workflow.add_node("retrieve", retrieve_node)
workflow.add_node("generate", generate_node)

workflow.add_edge(START, 'retrieve')
workflow.add_edge('retrieve', 'generate')
workflow.add_edge('generate', END)

app = workflow.compile()

def chat_with_bot(user_message, history):
    initial_state = {"question":user_message, "messages":[], "context":"","answer":""}
    final_state = app.invoke(initial_state)

    return final_state['answer']
gr.ChatInterface(fn=chat_with_bot, title = "JIO FAQ BOT", description = "Ask me anything about Jio Plans, 5G, or services").launch(server_name="0.0.0.0", server_port=7860)