import json
import re as _re

answer = """```json
{"name": "get_weather", "parameters": {"city": "Goa"}}
```"""

json_match = _re.search(r'(\{[\s\S]*"name"\s*:\s*"get_(weather|current_location)"[\s\S]*\})', answer)
if json_match:
    print("Match found!")
    matched_str = json_match.group(1)
    print("Matched string:", matched_str)
    try:
        parsed = json.loads(matched_str)
        print("Parsed:", parsed)
        tool_args = parsed.get("parameters", {}) or parsed.get("arguments", {})
        print("Tool args:", tool_args)
    except Exception as e:
        print("Exception:", e)
else:
    print("No match")
