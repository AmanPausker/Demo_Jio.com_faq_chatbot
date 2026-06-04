import difflib
import re

JIO_DICTIONARY = [
    "Jio", "Fiber", "AirFiber", "Postpaid", "Prepaid", 
    "Jio Plus", "Jio Fiber", "Jio AirFiber", "Jio Cinema", 
    "Jio Saavn", "Jio Mart", "Hotstar", "Netflix", "Amazon", 
    "Swiggy", "Zomato", "MyJio", "JioTV"
]

def fuzzy_replace(match):
    word = match.group(0)
    if len(word) <= 2 and word.lower() not in ["4g", "5g"]:
        return word
        
    # Check if the word exactly matches something to avoid unnecessary processing
    if word.title() in JIO_DICTIONARY or word in JIO_DICTIONARY:
        return word
        
    # Find the best match in the dictionary
    close_matches = difflib.get_close_matches(word.title(), JIO_DICTIONARY, n=1, cutoff=0.75)
    if close_matches:
        return close_matches[0]
        
    return word

queries = [
    "what is jioplus",
    "tell me about siggy offers",
    "how to recharge myjio app",
    "what are the plans for jiofiber",
    "i want jio plus", # Should not be altered
    "what is jiocinema"
]

for q in queries:
    corrected = re.sub(r'\b[A-Za-z]+\b', fuzzy_replace, q)
    print(f"Original: {q}\nCorrected: {corrected}\n")
