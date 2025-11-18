"""
Test script for debate endpoint
Run this after starting the backend server
"""

import requests
import json

# Backend URL
BASE_URL = "http://localhost:8000"

def test_debate():
    """Test the /api/debate endpoint"""
    
    print("🧪 Testing Debate Mode Endpoint\n")
    
    # Test data
    payload = {
        "topic": "Should I use React or Vue for my next web project?",
        "rounds": 3,
        "session_id": "test-session-123"
    }
    
    print(f"📤 Sending request to {BASE_URL}/api/debate")
    print(f"   Topic: {payload['topic']}")
    print(f"   Rounds: {payload['rounds']}\n")
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/debate",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=300  # 5 minutes timeout
        )
        
        if response.status_code == 200:
            data = response.json()
            print("✅ SUCCESS! Debate completed\n")
            print(f"📊 Results:")
            print(f"   Debate ID: {data.get('debate_id')}")
            print(f"   Topic: {data.get('topic')}")
            print(f"   Total Tokens: {data.get('total_tokens')}")
            print(f"   Total Cost: ${data.get('total_cost')}")
            print(f"   Rounds: {len(data.get('rounds', []))}")
            
            print("\n📝 Round Summary:")
            for round_data in data.get('rounds', []):
                print(f"   Round {round_data['round_num']}: {round_data['model']} ({round_data['role']})")
                print(f"      Tokens: {round_data['tokens']}, Cost: ${round_data['cost']}")
                print(f"      Preview: {round_data['content'][:100]}...")
            
            print("\n🏆 Final Solution:")
            final = data.get('final_solution', {})
            print(f"   Model: {final.get('model')}")
            print(f"   Tokens: {final.get('tokens')}")
            print(f"   Cost: ${final.get('cost')}")
            print(f"   Preview: {final.get('content', '')[:150]}...")
            
            # Save full response to file
            with open('debate_result.json', 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print("\n💾 Full response saved to debate_result.json")
            
        else:
            print(f"❌ ERROR: {response.status_code}")
            print(f"   Response: {response.text}")
            
    except requests.exceptions.ConnectionError:
        print("❌ Connection Error: Make sure the backend is running on http://localhost:8000")
    except requests.exceptions.Timeout:
        print("❌ Timeout: The debate took too long (>2 minutes)")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_debate()
