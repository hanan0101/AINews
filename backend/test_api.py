# This file is part of the AI newsletter system.
from backend.pipeline.modeling.gemini_client import generate_json


response = generate_json(
    "Return a JSON object with one key named message.",
    "Say hello",
    model="gemini-2.5-flash",
)
print(response)
