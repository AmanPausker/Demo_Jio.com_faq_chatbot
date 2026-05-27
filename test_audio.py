import requests

with open("mock.wav", "rb") as f:
    files = {'audio': ('mock.wav', f, 'audio/wav')}
    response = requests.post('http://localhost:8000/api/chat/audio', files=files)
    print(response.status_code)
    print(response.text)
