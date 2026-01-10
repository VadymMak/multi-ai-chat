"""
Test script for coding context detection in chat router.
Demonstrates how the system detects coding conversations and adjusts token limits.
"""

from app.routers.chat import detect_coding_context

# Test cases with different types of conversations

# Test 1: General conversation (no coding)
general_messages = [
    {"text": "Hello, how are you?", "sender": "user"},
    {"text": "I'm doing well, thank you! How can I help you today?", "sender": "assistant"},
    {"text": "I'm looking for restaurant recommendations in Paris", "sender": "user"},
]

# Test 2: Light coding context
light_coding_messages = [
    {"text": "I need help with a Python script", "sender": "user"},
    {"text": "Sure, I can help. What do you need?", "sender": "assistant"},
    {"text": "How do I read a file in Python?", "sender": "user"},
    {"text": "You can use the open() function with a context manager", "sender": "assistant"},
]

# Test 3: Moderate coding context
moderate_coding_messages = [
    {"text": "I'm getting an error in my React app", "sender": "user"},
    {"text": "```javascript\nconst App = () => {\n  return <div>Hello</div>\n}\n```", "sender": "assistant"},
    {"text": "I see a TypeError: undefined is not a function", "sender": "user"},
    {"text": "Let's check your imports and exports in App.tsx", "sender": "assistant"},
]

# Test 4: High coding context
high_coding_messages = [
    {"text": "Here's my code:\n```python\ndef process_data(data):\n    import pandas as pd\n    df = pd.DataFrame(data)\n    return df.to_json()\n```", "sender": "user"},
    {"text": "I see several issues. Let me help you refactor this:\n```python\nimport pandas as pd\n\ndef process_data(data: list) -> str:\n    \"\"\"Process data and return JSON.\"\"\"\n    df = pd.DataFrame(data)\n    return df.to_json()\n```", "sender": "assistant"},
    {"text": "Now I'm getting: ImportError: No module named pandas", "sender": "user"},
    {"text": "You need to install pandas. Run: pip install pandas", "sender": "assistant"},
    {"text": "Also update your requirements.txt file", "sender": "assistant"},
]

def run_test(name: str, messages: list):
    """Run detection test and print results."""
    print(f"\n{'='*60}")
    print(f"Test: {name}")
    print(f"{'='*60}")
    
    result = detect_coding_context(messages)
    
    print(f"Is Coding: {result['is_coding']}")
    print(f"Confidence: {result['confidence']:.2f}")
    print(f"Suggested Token Limit: {result['suggested_limit']}")
    print(f"Default Token Limit: 6000")
    print(f"Limit Increase: +{result['suggested_limit'] - 6000}")
    
    if result['indicators']:
        print(f"\nActive Indicators:")
        for indicator in result['indicators']:
            count = result.get('indicator_counts', {}).get(indicator, 0)
            print(f"  - {indicator}: {count:.1f}")
    else:
        print("\nNo coding indicators detected")
    
    # Interpretation
    if result['confidence'] >= 0.7:
        print("\n💡 Interpretation: HIGH coding context detected")
        print("   → Ideal for complex debugging, refactoring, or architecture discussions")
    elif result['confidence'] >= 0.5:
        print("\n💡 Interpretation: MODERATE coding context detected")
        print("   → Good for code reviews, API discussions, or algorithm explanations")
    elif result['confidence'] >= 0.3:
        print("\n💡 Interpretation: LIGHT coding context detected")
        print("   → Suitable for basic programming questions or file operations")
    else:
        print("\n💡 Interpretation: General conversation")
        print("   → Non-technical or minimal coding discussion")

if __name__ == "__main__":
    print("="*60)
    print("CODING CONTEXT DETECTION TEST SUITE")
    print("="*60)
    
    run_test("General Conversation", general_messages)
    run_test("Light Coding Context", light_coding_messages)
    run_test("Moderate Coding Context", moderate_coding_messages)
    run_test("High Coding Context", high_coding_messages)
    
    print(f"\n{'='*60}")
    print("Test suite completed!")
    print(f"{'='*60}\n")
    
    print("📊 Token Limit Summary:")
    print("  • Default (non-coding):     6,000 tokens")
    print("  • Light coding context:     7,000 tokens (+1,000)")
    print("  • Moderate coding context:  9,000 tokens (+3,000)")
    print("  • High coding context:     12,000 tokens (+6,000)")
    
    print("\n🔍 Detection Criteria:")
    print("  • Code blocks (```) - Strong indicator")
    print("  • File extensions (.py, .js, etc.)")
    print("  • Programming keywords (def, class, import, etc.)")
    print("  • Error messages (exception, traceback, etc.)")
    print("  • API patterns (GET, POST, REST, etc.)")
    print("  • Function signatures")
    print("  • Import statements")
    
    print("\n✅ Integration: This detection runs automatically on:")
    print("  • GET /api/chat/last-session-by-role")
    print("  • GET /api/chat/last-session")
    print("  • GET /api/chat/history")
    print("  • GET /api/chat/debug/coding-context (debug endpoint)")
