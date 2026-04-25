"""Phase 2 Demo — The Architect: end-to-end autonomous organism lifecycle.

This script:
1. Seeds a fresh organism with a multi-step goal
2. Sends it through multiple perception cycles
3. Watches it reason, forge tools, use them, and act on results
"""
import asyncio
import json
from backend.genesis import runtime, store

async def main():
    # Clean start — delete old Architect if exists
    import shutil
    from pathlib import Path
    for oid in ["o_85b9ebd51972", "o_1c04684e1514"]:
        p = Path(f"organisms/{oid}")
        if p.exists():
            shutil.rmtree(p)
            print(f"  Cleaned up old organism {oid}")

    # Seed a brand new organism
    org = runtime.seed(
        name="NewsBot",
        intent_goal=(
            "Fetch the top 3 headlines from HackerNews using fetch_web_page "
            "(url: https://news.ycombinator.com) and send a summary to "
            "Slack channel #general. Then declare_done."
        ),
        constraints=["Only use built-in tools, do NOT use forge_mcp_server"],
        forbidden=["Do not call forge_mcp_server"],
    )
    print(f"\n🌱 Organism seeded: {org.id} — {org.name}")
    print(f"   Intent: {org.intent.goal[:80]}...")

    # Run 3 perception cycles
    for i in range(3):
        print(f"\n{'='*60}")
        print(f"  🔄 Perception cycle {i+1}")
        print(f"{'='*60}")

        decision = await runtime.perceive(
            org.id,
            {"type": "tick", "source": "interval", "cycle": i+1},
        )

        print(f"  💭 Reasoning: {decision.reasoning[:120]}...")
        print(f"  ⚡ Action: {decision.action['name']}({json.dumps(decision.action.get('args', {}))[:100]})")

        result_ok = decision.result.get("ok") if isinstance(decision.result, dict) else "?"
        print(f"  {'✅' if result_ok else '❌'} Result OK: {result_ok}")

        if isinstance(decision.result, dict):
            for k, v in decision.result.items():
                if k != "ok":
                    val = str(v)[:120]
                    print(f"     {k}: {val}")

        if decision.action.get("name") == "declare_done":
            print(f"\n🎉 Organism declared done!")
            break

    # Show final state
    org = store.load_organism(org.id)
    decisions = store.all_decisions(org.id)
    print(f"\n📊 Final State:")
    print(f"   Organism: {org.name} ({org.id})")
    print(f"   State: {org.state}")
    print(f"   Fitness: {org.fitness_score:.2f}")
    print(f"   Total decisions: {len(decisions)}")
    print(f"   Patterns learned: {len(org.learned_patterns)}")

if __name__ == "__main__":
    asyncio.run(main())
