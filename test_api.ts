const parsed = {
"tool" :"get_weather",
"param":{
"city":"goa"
}
};
let tool_args = parsed.parameters || parsed.arguments || parsed.param || parsed.params || parsed.args;
if (!tool_args) {
  tool_args = { ...parsed };
  delete (tool_args as any).name;
  delete (tool_args as any).tool;
  delete (tool_args as any).action;
}
console.log(JSON.stringify({ tool_name: parsed.tool, tool_args }));
