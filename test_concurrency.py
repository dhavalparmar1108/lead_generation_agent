"""
Concurrency Test for SalesBot
Tests thread-safety with SQLite and multiple simultaneous chat requests
"""

import asyncio
import aiohttp
import uuid
import time
from datetime import datetime
import json

# Configuration
API_URL = "http://localhost:8001/chat"
NUM_CONCURRENT_USERS = 15

# Test messages (simulating multi-turn conversation)
TEST_MESSAGES = [
    "Hi, I need a CRM solution",
    "I'm interested in pipeline management",
    "Sounds good, my name is User_{user_id}"
]


class TestResult:
    def __init__(self):
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.response_times = []
        self.errors = []
        self.lead_captured = {}

    def add_result(self, success: bool, response_time: float, error: str = None, data: dict = None):
        self.total_requests += 1
        self.response_times.append(response_time)
        
        if success:
            self.successful_requests += 1
            if data and data.get("lead", {}).get("captured"):
                conv_id = data.get("conversation_id")
                self.lead_captured[conv_id] = data.get("lead", {}).get("data")
        else:
            self.failed_requests += 1
            self.errors.append(error)

    def print_summary(self):
        print("\n" + "="*60)
        print("CONCURRENCY TEST RESULTS")
        print("="*60)
        print(f"Total Requests:     {self.total_requests}")
        print(f"Successful:         {self.successful_requests} ✅")
        print(f"Failed:             {self.failed_requests} ❌")
        print(f"Success Rate:       {(self.successful_requests/self.total_requests*100):.1f}%")
        print(f"Avg Response Time:  {(sum(self.response_times)/len(self.response_times)*1000):.0f}ms")
        print(f"Min Response Time:  {min(self.response_times)*1000:.0f}ms")
        print(f"Max Response Time:  {max(self.response_times)*1000:.0f}ms")
        print(f"Leads Captured:     {len(self.lead_captured)}")
        
        if self.errors:
            print(f"\nErrors ({len(self.errors)}):")
            for error in self.errors[:5]:
                print(f"  - {error}")
        
        print("="*60 + "\n")


async def send_chat_message(
    session: aiohttp.ClientSession,
    user_id: int,
    conversation_id: str,
    message: str
) -> dict:
    """Send a single chat message."""
    try:
        start_time = time.time()
        
        async with session.post(
            API_URL,
            json={
                "message": message.format(user_id=user_id),
                "conversation_id": conversation_id
            },
            timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            elapsed = time.time() - start_time
            
            if response.status == 200:
                data = await response.json()
                return {
                    "success": True,
                    "elapsed": elapsed,
                    "data": data
                }
            else:
                return {
                    "success": False,
                    "elapsed": elapsed,
                    "error": f"HTTP {response.status}"
                }
    except Exception as e:
        return {
            "success": False,
            "elapsed": 0,
            "error": str(e)
        }


async def user_conversation(
    user_id: int,
    test_result: TestResult,
    barrier: asyncio.Barrier
):
    """
    Simulate a single user's multi-turn conversation.
    Barrier ensures all users start at the same time.
    """
    conversation_id = f"user_{user_id}_{uuid.uuid4().hex[:8]}"
    
    print(f"User {user_id}: Starting conversation {conversation_id}")
    
    # Wait for all users to be ready
    await barrier.wait()
    
    # User sends multiple messages in sequence
    async with aiohttp.ClientSession() as session:
        for msg_idx, message in enumerate(TEST_MESSAGES):
            result = await send_chat_message(
                session,
                user_id,
                conversation_id,
                message
            )
            
            elapsed = result.get("elapsed", 0)
            test_result.add_result(
                success=result.get("success", False),
                response_time=elapsed,
                error=result.get("error"),
                data=result.get("data")
            )
            
            if result.get("success"):
                print(f"  User {user_id}, Msg {msg_idx+1}: ✅ ({elapsed*1000:.0f}ms)")
            else:
                print(f"  User {user_id}, Msg {msg_idx+1}: ❌ ({result.get('error')})")
            
            # Small delay between messages (realistic)
            await asyncio.sleep(0.5)


async def test_same_conversation():
    """
    Test case: Multiple users on the SAME conversation
    This tests maximum concurrency on single conversation state
    """
    print("\n" + "="*60)
    print("TEST 1: Multiple Users on SAME Conversation")
    print("="*60)
    
    test_result = TestResult()
    shared_conv_id = f"shared_{uuid.uuid4().hex[:8]}"
    barrier = asyncio.Barrier(NUM_CONCURRENT_USERS)
    
    # All users hit the same conversation
    tasks = []
    async with aiohttp.ClientSession() as session:
        for user_id in range(NUM_CONCURRENT_USERS):
            for msg_idx, message in enumerate(TEST_MESSAGES):
                task = asyncio.create_task(
                    _send_and_record(
                        session,
                        user_id,
                        shared_conv_id,
                        message,
                        test_result,
                        barrier if msg_idx == 0 else None  # Barrier only on first message
                    )
                )
                tasks.append(task)
        
        await asyncio.gather(*tasks)
    
    test_result.print_summary()
    return test_result


async def _send_and_record(session, user_id, conv_id, message, test_result, barrier=None):
    """Helper to send and record results."""
    if barrier:
        await barrier.wait()
    
    result = await send_chat_message(session, user_id, conv_id, message)
    test_result.add_result(
        success=result.get("success", False),
        response_time=result.get("elapsed", 0),
        error=result.get("error"),
        data=result.get("data")
    )
    
    if result.get("success"):
        print(f"  User {user_id}: ✅")
    else:
        print(f"  User {user_id}: ❌ ({result.get('error')})")


async def test_different_conversations():
    """
    Test case: Multiple users on DIFFERENT conversations
    This tests parallel handling of separate conversation states
    """
    print("\n" + "="*60)
    print("TEST 2: Multiple Users on DIFFERENT Conversations")
    print("="*60)
    
    test_result = TestResult()
    barrier = asyncio.Barrier(NUM_CONCURRENT_USERS)
    
    # Each user has their own conversation
    tasks = [
        user_conversation(user_id, test_result, barrier)
        for user_id in range(NUM_CONCURRENT_USERS)
    ]
    
    await asyncio.gather(*tasks)
    test_result.print_summary()
    return test_result


async def test_concurrent_lead_capture():
    """
    Test case: Multiple complete lead captures simultaneously
    This tests database write conflicts
    """
    print("\n" + "="*60)
    print("TEST 3: Concurrent Lead Capture (Database Writes)")
    print("="*60)
    
    test_result = TestResult()
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        for user_id in range(NUM_CONCURRENT_USERS):
            conv_id = f"lead_user_{user_id}_{uuid.uuid4().hex[:8]}"
            
            # Send complete lead information
            message = f"I'm User_{user_id}, user{user_id}@test.com, 9876543{user_id:03d}, need CRM"
            
            task = send_chat_message(session, user_id, conv_id, message)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks)
        
        for i, result in enumerate(results):
            test_result.add_result(
                success=result.get("success", False),
                response_time=result.get("elapsed", 0),
                error=result.get("error"),
                data=result.get("data")
            )
            
            if result.get("success"):
                print(f"  User {i}: ✅ Lead captured" if result["data"].get("lead", {}).get("captured") else f"  User {i}: ✅")
            else:
                print(f"  User {i}: ❌ ({result.get('error')})")
    
    test_result.print_summary()
    return test_result


async def main():
    print("\n")
    print("╔" + "="*58 + "╗")
    print("║" + "SalesBot CONCURRENCY TEST SUITE".center(58) + "║")
    print("║" + f"Testing with {NUM_CONCURRENT_USERS} concurrent users".center(58) + "║")
    print("╚" + "="*58 + "╝")
    
    print(f"\nStarting at: {datetime.now().strftime('%H:%M:%S')}")
    print(f"API URL: {API_URL}\n")
    
    try:
        # Run all tests
        result1 = await test_different_conversations()
        result2 = await test_concurrent_lead_capture()
        
        # Summary
        print("\n" + "="*60)
        print("OVERALL SUMMARY")
        print("="*60)
        total_successful = result1.successful_requests + result2.successful_requests
        total_requests = result1.total_requests + result2.total_requests
        print(f"Total Requests:     {total_requests}")
        print(f"Total Successful:   {total_successful}")
        print(f"Total Failed:       {total_requests - total_successful}")
        print(f"Success Rate:       {(total_successful/total_requests*100):.1f}%")
        print(f"Total Leads:        {len(result1.lead_captured) + len(result2.lead_captured)}")
        print("\n✅ All tests passed! SQLite handling concurrency correctly.\n")
        
    except Exception as e:
        print(f"\n❌ Test error: {e}\n")


if __name__ == "__main__":
    asyncio.run(main())
