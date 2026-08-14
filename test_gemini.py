import os
from google import genai
from google.genai import types
from PIL import Image

client = genai.Client(
    api_key=os.environ["GOOGLE_API_KEY"]
)

MODEL_NAME = "gemini-3.5-flash-lite"

image = Image.open(
    "images/staff_processing/shelfmessing/shelf_2.jpg"
)

prompt = """
Analyze this shelf image.

Return ONLY JSON:

{
  "products": [
    {
      "description": "...",
      "brand": "...",
      "confidence": "high|medium|low"
    }
  ],
  "notes": "..."
}
"""

response = client.models.generate_content(
    model=MODEL_NAME,
    contents=[prompt, image],
    config=types.GenerateContentConfig(
        response_mime_type="application/json"
    )
)

print(response.text)