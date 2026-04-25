import asyncio
from backend.genesis import runtime

async def wake():
    await runtime.perceive("o_85b9ebd51972", {"type": "system_startup", "source": "system", "text": "Organism booted. Begin your intent."})

if __name__ == "__main__":
    asyncio.run(wake())
