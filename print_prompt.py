import asyncio
from backend.genesis import runtime, store
org = store.load_organism("o_85b9ebd51972")
prompt = runtime._build_prompt(org, {"type": "wakeup"}, [], [], runtime._builtin_tool_catalog())
print(f"Prompt length in chars: {len(prompt)}")
print(prompt)
