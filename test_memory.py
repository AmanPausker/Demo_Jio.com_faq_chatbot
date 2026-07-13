import asyncio
import os
from dotenv import load_dotenv

load_dotenv(override=True)
from nodes import evaluate_and_save_memory_bg

async def main():
    await evaluate_and_save_memory_bg(
        question="I live in Delhi.",
        answer="That's nice! Delhi is a great city.",
        user_id="test_user_123",
        token=""
    )

if __name__ == "__main__":
    asyncio.run(main())
