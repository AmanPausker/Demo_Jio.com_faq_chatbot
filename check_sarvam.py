from sarvamai import SarvamAI, AsyncSarvamAI
print("SarvamAI:", [x for x in dir(SarvamAI) if not x.startswith('_')])
print("AsyncSarvamAI:", [x for x in dir(AsyncSarvamAI) if not x.startswith('_')])
