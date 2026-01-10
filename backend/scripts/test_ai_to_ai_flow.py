# File: scripts/test_ai_to_ai_flow.py

import requests
import uuid
import time

BASE_URL = "http://localhost:8000/api"  # Change if different
role_id = 1                         # Adjust to match a real role in your DB
project_id = "1"                    # Adjust to match a real project in your DB
session_id = str(uuid.uuid4())

print("🧪 Starting AI-to-AI Test Flow")
print(f"🎯 Session ID: {session_id}\n")

# Helper function for safe JSON debug output
def print_response(resp, label):
    print(f"\n✅ {label} ({resp.status_code})")
    try:
        data = resp.json()
        print("↪ JSON keys:", list(data.keys()))
        if "reply" in data:
            print("🧠 Reply:", data["reply"][:100])
        if "summary" in data:
            print("📝 Summary:", data["summary"][:100])
        return data
    except Exception as e:
        print(f"❌ Failed to parse JSON: {e}")
        print("↪ Raw Response:", resp.text)
        return None

# 1️⃣ /ask — initial user message
step1_payload = {
    "role": role_id,
    "project_id": project_id,
    "chat_session_id": session_id,
    "message": "What are the main steps to build a smart assistant?"
}
resp1 = requests.post(f"{BASE_URL}/ask", json=step1_payload)
data1 = print_response(resp1, "Step 1: /ask")

time.sleep(1)

# 2️⃣ /ask-ai-to-ai — Boost mode (OpenAI as starter)
step2_payload = {
    "topic": "How can this assistant support multiple users and projects?",
    "starter": "openai",
    "role": role_id,
    "project_id": project_id,
    "chat_session_id": session_id
}
resp2 = requests.post(f"{BASE_URL}/ask-ai-to-ai", json=step2_payload)
data2 = print_response(resp2, "Step 2: /ask-ai-to-ai")

time.sleep(1)

# 3️⃣ /ask — follow-up question
step3_payload = {
    "role": role_id,
    "project_id": project_id,
    "chat_session_id": session_id,
    "message": "Can you summarize everything we've discussed so far?"
}
resp3 = requests.post(f"{BASE_URL}/ask", json=step3_payload)
data3 = print_response(resp3, "Step 3: /ask follow-up")

print("\n✅ Test Complete — Check DB or Swagger for message persistence.")
print(f"💾 Session ID used: {session_id}")
