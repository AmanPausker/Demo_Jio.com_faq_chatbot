

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

from get_transcript import listen_for_speech

from get_audio import generate_speech

async def process_text(user_message, history):
    if not user_message:
        yield "", history, None
        return
    initial_state = {"question": user_message, "messages": [], "context": "", "answer": ""}
    final_state = await app.ainvoke(initial_state)
    answer = final_state['answer']
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": answer})
    
    yield "", history, None
    
    # Generate TTS
    async for audio_chunk in generate_speech(answer):
        yield "", history, audio_chunk

async def process_audio(history):
    # This triggers the server-side microphone
    user_message = await listen_for_speech(silence_timeout=2.0)
    
    if not user_message.strip():
        history.append({"role": "assistant", "content": "🎤 [Audio Mode] No speech detected. Please try speaking again."})
        yield history, None
        return
        
    initial_state = {"question": user_message, "messages": [], "context": "", "answer": ""}
    final_state = await app.ainvoke(initial_state)
    answer = final_state['answer']
    history.append({"role": "user", "content": f"(User-Audio) {user_message}"})
    history.append({"role": "assistant", "content": answer})
    
    yield history, None
    
    # Generate TTS
    async for audio_chunk in generate_speech(answer):
        yield history, audio_chunk

with gr.Blocks(title="JIO FAQ BOT") as demo:
    gr.Markdown("# JIO FAQ BOT\nAsk me anything about Jio Plans, 5G, or services")
    
    chatbot = gr.Chatbot()
    audio_out = gr.Audio(visible=True, autoplay=True, label="Bot Voice Response", streaming=True)
    
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