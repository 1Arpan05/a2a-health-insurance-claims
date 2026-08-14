import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI()

api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    raise ValueError("OPENAI_API_KEY is not set in the environment variables.")

client = OpenAI(api_key=api_key)