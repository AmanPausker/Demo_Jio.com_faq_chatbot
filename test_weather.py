import os
from dotenv import load_dotenv
load_dotenv(override=True)
from tools import get_weather

print(get_weather.invoke({"city": "Goa"}))
