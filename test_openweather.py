from dotenv import load_dotenv
load_dotenv(override = True)
import os
import requests
API_KEY = os.getenv("OPEN_WEATHER_API_KEY")

def get_weather(city:str)->str:

    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "q" :city,
        "appid" : API_KEY,
        "units":"metric"
    }
    response = requests.get(url,params=params)
    data = response.json()

    if response.status_code != 200:
        return f"Error: {data}"
    import json
    return json.dumps({
        "type": "WeatherCard",
        "props": {
            "city": data['name'],
            "temperature": data['main']['temp'],
            "condition": data['weather'][0]['description']
        }
    })
print(get_weather("Goa"))