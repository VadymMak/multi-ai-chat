import requests
import sys

BASE = "http://localhost:8000/api"
ROLE_ID = 5
PROJECT_ID = 2
PROVIDER = "openai"           # or "anthropic" or "all"
USER_TEXT = "Integration test message via test_whole_flow.py"

def get_last_session(role_id: int, project_id: int):
    r = requests.get(f"{BASE}/chat/last-session-by-role",
                     params={"role_id": role_id, "project_id": project_id})
    r.raise_for_status()
    return r.json()

def ask(query: str, role_id: int, project_id: int, provider: str, chat_session_id: str | None):
    payload = {
        "query": query,
        "provider": provider,
        "role_id": role_id,
        "project_id": project_id,
    }
    if chat_session_id:
        payload["chat_session_id"] = chat_session_id

    r = requests.post(f"{BASE}/ask", json=payload, headers={"Content-Type": "application/json"})
    r.raise_for_status()
    return r.json()

def main():
    # 1) Fetch last session
    s = get_last_session(ROLE_ID, PROJECT_ID)
    session_id = s.get("chat_session_id")
    print("Session ID:", session_id)

    # 2) Send a user message to /ask with the correct keys
    resp = ask(USER_TEXT, ROLE_ID, PROJECT_ID, PROVIDER, session_id)
    print("Ask response:", resp)

    # Prefer the session id the backend returns (in case it rotates/creates one)
    session_id = resp.get("chat_session_id", session_id)

    # 3) Read back the session to confirm the message got stored
    s2 = get_last_session(ROLE_ID, PROJECT_ID)
    msgs = s2.get("messages", [])
    print("Updated messages (tail):", msgs[-3:])  # show last few

if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print("HTTP error:", e.response.status_code, e.response.text)
        sys.exit(1)
    except Exception as e:
        print("Error:", e)
        sys.exit(1)
