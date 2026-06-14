import gradio as gr
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



from get_transcript import listen_for_speech

from get_audio import generate_speech

async def process_text(user_message, history):
    if not user_message:
        yield "", history, None
        return
        
    history.append({"role": "user", "content": user_message})
    yield "", history, None
    
    initial_state = {"question": user_message, "messages": [], "context": "", "answer": ""}
    final_state = await app.ainvoke(initial_state)
    answer = final_state['answer']
    history.append({"role": "assistant", "content": answer})
    
    yield "", history, None
    
    # Generate TTS concurrently and return final tuple
    audio_tuple = await generate_speech(answer)
    yield "", history, audio_tuple

async def process_audio(history):
    # This triggers the server-side microphone
    user_message = await listen_for_speech(silence_timeout=0.5)
    
    if not user_message.strip():
        history.append({"role": "assistant", "content": "🎤 [Audio Mode] No speech detected. Please try speaking again."})
        yield history, None
        return
        
    history.append({"role": "user", "content": f"(User-Audio) {user_message}"})
    yield history, None
    
    initial_state = {"question": user_message, "messages": [], "context": "", "answer": ""}
    final_state = await app.ainvoke(initial_state)
    answer = final_state['answer']
    history.append({"role": "assistant", "content": answer})
    
    yield history, None
    
    # Generate TTS concurrently and return final tuple
    audio_tuple = await generate_speech(answer)
    yield history, audio_tuple

with gr.Blocks(title="JIO FAQ BOT") as demo:
    gr.Markdown("# JIO FAQ BOT\nAsk me anything about Jio Plans, 5G, or services")
    
    chatbot = gr.Chatbot()
    audio_out = gr.Audio(visible=True, autoplay=True, label="Bot Voice Response")
    
    with gr.Row():
        with gr.Column(scale=8):
            msg = gr.Textbox(show_label=False, placeholder="Type your question here...")
        with gr.Column(scale=1):
            text_btn = gr.Button("Send")
        with gr.Column(scale=1):
            audio_btn = gr.Button("🎤")

    msg.submit(process_text, inputs=[msg, chatbot], outputs=[msg, chatbot, audio_out])
    text_btn.click(process_text, inputs=[msg, chatbot], outputs=[msg, chatbot, audio_out])
    audio_btn.click(process_audio, inputs=[chatbot], outputs=[chatbot, audio_out])

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)