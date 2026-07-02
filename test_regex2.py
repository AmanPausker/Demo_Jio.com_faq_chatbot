import re as _re

answer = """{
"tool" :"get_weather",
"param":{
"city":"goa"
}
}"""

json_match = _re.search(r'(\{[\s\S]*"(name|tool)"\s*:\s*"get_(weather|current_location)"[\s\S]*\})', answer)
if json_match:
    print("Match found!")
else:
    print("No match")
