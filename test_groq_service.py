#!/usr/bin/env python3

import asyncio
import logging
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.groq import groq_service, ChatMessage, ChatRole

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_simple_chat():
    print("\n🧪 Testing simple chat...")
    try:
        response = await groq_service.simple_chat(
            message="Tell me a short programming joke",
            model="openai/gpt-oss-20b",
            max_tokens=100
        )
        print(f"✅ Simple chat response: {response}")
        return True
    except Exception as e:
        print(f"❌ Simple chat failed: {e}")
        return False


async def test_chat_with_system_prompt():
    print("\n🧪 Testing chat with system prompt...")
    try:
        response = await groq_service.chat_with_system_prompt(
            system_prompt="You are a helpful coding assistant. Respond concisely.",
            user_message="What is Python?",
            model="openai/gpt-oss-20b",
            max_tokens=80
        )
        print(f"✅ System prompt chat response: {response}")
        return True
    except Exception as e:
        print(f"❌ System prompt chat failed: {e}")
        return False


async def test_multi_turn_chat():
    print("\n🧪 Testing multi-turn chat...")
    try:
        messages = [
            ChatMessage(role=ChatRole.USER, content="Hello! What's 2+2?"),
            ChatMessage(role=ChatRole.ASSISTANT, content="Hello! 2+2 equals 4."),
            ChatMessage(role=ChatRole.USER, content="Great! Now what's 4+4?")
        ]

        response = await groq_service.multi_turn_chat(
            messages=messages,
            model="openai/gpt-oss-20b",
            max_tokens=50
        )
        print(f"✅ Multi-turn chat response: {response}")
        return True
    except Exception as e:
        print(f"❌ Multi-turn chat failed: {e}")
        return False


async def test_health_check():
    print("\n🧪 Testing health check...")
    try:
        is_healthy = await groq_service.health_check()
        if is_healthy:
            print("✅ Health check passed")
            return True
        else:
            print("❌ Health check failed")
            return False
    except Exception as e:
        print(f"❌ Health check error: {e}")
        return False


async def main():
    print("🚀 Starting Groq Service Tests")
    print("=" * 50)

    tests = [
        ("Health Check", test_health_check),
        ("Simple Chat", test_simple_chat),
        ("System Prompt Chat", test_chat_with_system_prompt),
        ("Multi-turn Chat", test_multi_turn_chat),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} crashed: {e}")
            results.append((test_name, False))

    print("\n" + "=" * 50)
    print("📊 TEST RESULTS SUMMARY")
    print("=" * 50)

    passed = 0
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{test_name}: {status}")
        if result:
            passed += 1

    print(f"\nTotal: {passed}/{len(results)} tests passed")

    if passed == len(results):
        print("🎉 All tests passed! Groq service is working correctly.")
    else:
        print("⚠️  Some tests failed. Check the errors above.")


if __name__ == "__main__":
    asyncio.run(main())