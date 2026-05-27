import gradio as gr
import time
import numpy as np

def stream_audio():
    # simulate chunks
    for i in range(5):
        time.sleep(1)
        sr = 16000
        t = np.linspace(0, 1, sr, False)
        # generate a beep
        data = np.sin(2*np.pi*440*t) * (2**15 - 1)
        yield (sr, data.astype(np.int16))

with gr.Blocks() as demo:
    btn = gr.Button("Play")
    # try with streaming=True
    audio_out = gr.Audio(autoplay=True, streaming=True)
    btn.click(stream_audio, outputs=audio_out)

if __name__ == "__main__":
    demo.launch(prevent_thread_lock=True)
