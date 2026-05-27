import re

question = "Tell me about Jio Plus"
jio_compounds = re.findall(r'(?i)\bjio\s+\w+\b', question)

# If we replace the compounds in the question with the glued versions:
for compound in jio_compounds:
    glued = compound.replace(" ", "")
    # Note: re.sub with ignorecase might be better, but simple replace works for exact match
    question = re.sub(re.escape(compound), glued, question, flags=re.IGNORECASE)

print("Modified question:", question)

words = re.findall(r'\b\w+\b', question)
stopwords = {"is", "what", "how", "the", "a", "an", "for", "to", "in", "on", "of", "and", "or", "tell", "me", "about", "are", "do", "does", "i", "can", "something", "some"}
keywords = [w for w in words if w.lower() not in stopwords]

keyword_query = " OR ".join(keywords) if keywords else question
print("Keyword Query:", keyword_query)
