from langchain.tools import tool
import requests
import os
from dotenv import load_dotenv

load_dotenv(override=True)
open_weather_api_key = os.getenv("OPEN_WEATHER_API_KEY")

@tool
def get_weather(city:str)->str:
    """
    Get weather information for a city.
    """

    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "q" :city,
        "appid" : open_weather_api_key,
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

@tool
def get_current_location()->str:
    """
    Get the current location (city) of the user. 
    Call this tool when the user asks about weather 'here' or 'in my location' without specifying a city.
    Call this tool when the user wants to ask weather around his current location.
    """
    try:
        response = requests.get("http://ip-api.com/json/")
        data = response.json()
        if data.get("status") == "success":
            return data["city"]
        else:
            return "Unable to determine location."
    except Exception as e:
        return f"Error getting location: {e}"
