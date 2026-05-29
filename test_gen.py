from agent_state import GraphState
from nodes import generate_node
import asyncio

state = {
    "question": "tell me about jio plus",
    "messages": [],
    "context": """Topic: Postpaid Offerings | Subtopic: JioPlus | Question: What is JioPlus? | Answer: JioPlus is the all new Postpaid plans providing the best Postpaid service experience for up to 4 new connections per user. Features and benefits of JioPlus More Value Starting at ₹ 449 per month Additional 3 add-on connections @ ₹ 150 per SIM Total monthly charge of only ₹ 899 for a family of 4 (₹ 449 + ₹ 150 * 3) Effective monthly charge of ₹ 225 per SIM More Data Share data with your entire family No daily data limits Truly unlimited free 5G Data with Jio True 5G Welcome Offer More Benefits: Choice number / Premium content / International Roaming Mobile number of your choice Premium Applications like Netflix, Amazon, JioTV First-ever in-flight connectivity while traveling abroad India calling at ₹ 1 per minute with WiFi calling on international roaming One international roaming plan for 150+ countries More Privilege: No Security Deposit required for Existing mobile postpaid users of other operators Credit card users of Axis Bank, HDFC Bank and SBI Card More Care Priority call-back service by care-specialist on single-click More Convenience Move your existing number to Jio without any downtime Missed call on 70 000-70 000 for free home delivery & activation""",
    "answer": "",
    "router": "2"
}

res = generate_node(state)
print("ANSWER:")
print(res["answer"])
