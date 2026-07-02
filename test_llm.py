from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage
from tools import get_weather, get_current_location

client = ChatOllama(model="cow/gemma2_tools:2b", base_url="http://localhost:11434", temperature=0.7)
tools = [get_weather, get_current_location]
llm = client.bind_tools(tools)

from system_instructions import get_general_generation_prompt
prompt = get_general_generation_prompt("")

response = llm.invoke([
    SystemMessage(content=prompt),
    HumanMessage(content="What is the weather in Goa?")
])
print("Content:", response.content)
print("Tool calls:", getattr(response, 'tool_calls', None))
