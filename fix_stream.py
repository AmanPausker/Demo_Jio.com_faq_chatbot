import re

with open("server.py", "r") as f:
    content = f.read()

# Restore primary_llm
content = content.replace(
    'primary_llm = ChatOllama(model="cow/gemma2_tools:2b", base_url="http://localhost:11434", streaming=False, think=False)',
    'primary_llm = ChatOllama(model="cow/gemma2_tools:2b", base_url="http://localhost:11434", streaming=True, think=False)'
)

# Restore llm_producer
old_producer = """        async def llm_producer():
            \"\"\"Fetch full LLM response and enqueue ordered TTS tasks on sentence boundaries.\"\"\"
            nonlocal full_answer
            try:
                t_llm = time.time()
                response = await primary_llm.ainvoke(messages)
                
                if not session.is_processing or session.current_response_id != my_response_id:
                    logger.debug("[STREAM] LLM interrupted by barge-in.")
                    return
                
                full_answer = response.content
                logger.debug(f"[LATENCY] LLM finished: {(time.time() - t_llm)*1000:.0f}ms | chars={len(full_answer)}")
                
                try:
                    await websocket.send_json({"type": "text_chunk", "payload": full_answer})
                except Exception:
                    pass

                import re
                sentences = re.split(r'(?<=[.!?])\\s+', full_answer)
                for s in sentences:
                    stripped = s.strip()
                    if stripped and session.is_processing and session.current_response_id == my_response_id:
                        task = asyncio.create_task(fetch_tts_sentence(stripped))
                        await tts_queue.put(task)

            except Exception as e:
                live_logger.error(f"[STREAM] LLM error: {e}")"""

new_producer = """        async def llm_producer():
            \"\"\"Stream LLM tokens, enqueue ordered TTS tasks on sentence boundaries.\"\"\"
            nonlocal full_answer
            sentence_buffer = ""
            t_llm = time.time()
            first_token = True
            try:
                async for chunk in primary_llm.astream(messages):
                    if not session.is_processing or session.current_response_id != my_response_id:
                        logger.debug("[STREAM] LLM interrupted by barge-in.")
                        break
                    
                    # Try to extract reasoning token if content is empty
                    reasoning_token = ""
                    if hasattr(chunk, "additional_kwargs") and chunk.additional_kwargs:
                        reasoning_token = chunk.additional_kwargs.get("reasoning", "")
                        
                    token = chunk.content
                    if not token and not reasoning_token:
                        continue
                        
                    if reasoning_token:
                        # Send reasoning token to frontend so user knows bot is thinking, 
                        # but do NOT add to full_answer or TTS sentence_buffer
                        try:
                            await websocket.send_json({"type": "text_chunk", "payload": reasoning_token})
                        except Exception:
                            pass
                        continue
                        
                    full_answer += token
                    sentence_buffer += token
                    if first_token:
                        logger.debug(f"[LATENCY] LLM first token: {(time.time() - t_llm)*1000:.0f}ms")
                        first_token = False
                    try:
                        await websocket.send_json({"type": "text_chunk", "payload": token})
                    except Exception:
                        break
                    stripped = sentence_buffer.strip()
                    if stripped and stripped[-1] in SENTENCE_ENDINGS and len(stripped) >= MIN_SENTENCE_LEN:
                        task = asyncio.create_task(fetch_tts_sentence(stripped))
                        await tts_queue.put(task)
                        sentence_buffer = ""
                logger.debug(f"[LATENCY] LLM streaming done: {(time.time() - t_llm)*1000:.0f}ms | chars={len(full_answer)}")
            except Exception as e:
                live_logger.error(f"[STREAM] LLM streaming error: {e}")"""

content = content.replace(old_producer, new_producer)

# Restore finally block
old_finally = """            finally:
                if not full_answer and session.is_processing and session.current_response_id == my_response_id:
                    task = asyncio.create_task(fetch_tts_sentence("I'm having trouble thinking right now. Please try again."))
                    await tts_queue.put(task)

                await tts_queue.put(None)  # Sentinel"""

new_finally = """            finally:
                if not full_answer and session.is_processing and session.current_response_id == my_response_id:
                    task = asyncio.create_task(fetch_tts_sentence("I'm having trouble thinking right now. Please try again."))
                    await tts_queue.put(task)

                if sentence_buffer.strip() and session.is_processing and session.current_response_id == my_response_id:
                    task = asyncio.create_task(fetch_tts_sentence(sentence_buffer.strip()))
                    await tts_queue.put(task)
                await tts_queue.put(None)  # Sentinel"""

content = content.replace(old_finally, new_finally)

with open("server.py", "w") as f:
    f.write(content)
