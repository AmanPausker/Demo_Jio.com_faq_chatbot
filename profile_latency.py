import time
import asyncio
from agent_state import GraphState
from nodes import retrieve_node, generate_node
from get_audio import generate_speech

async def run_profiling():
    print("--- Starting Latency Profile ---")
    question = "Tell me about Jio Swiggy offers"
    
    # 1. Retrieve Node
    t0 = time.time()
    state = {"question": question, "messages": [], "context": "", "answer": ""}
    state.update(retrieve_node(state))
    t1 = time.time()
    print(f"[1] retrieve_node (Neo4j + CrossEncoder) took: {t1 - t0:.2f} seconds")
    
    # 2. Generate Node
    t2 = time.time()
    state.update(generate_node(state))
    t3 = time.time()
    print(f"[2] generate_node (Cerebras LLM) took: {t3 - t2:.2f} seconds")
    
    # 3. Generate Speech
    t4 = time.time()
    async for _ in generate_speech(state['answer']):
        pass
    t5 = time.time()
    print(f"[3] generate_speech (Sarvam TTS) took: {t5 - t4:.2f} seconds")
    
    print(f"Total end-to-end processing time: {t5 - t0:.2f} seconds")

if __name__ == "__main__":
    asyncio.run(run_profiling())
