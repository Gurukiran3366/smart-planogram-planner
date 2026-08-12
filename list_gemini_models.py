# list_gemini_models.py
import os
from google import genai

client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))

print("Available models that support generate_content:\n")
for model in client.models.list():
    if 'generateContent' in model.supported_actions:
        print(f"  ✅ {model.name}")
    else:
        print(f"  ⏸  {model.name} (not usable for content generation)")