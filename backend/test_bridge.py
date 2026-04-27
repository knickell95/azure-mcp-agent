"""
Standalone validation script for MCPBridge.
Run from repo root:  .venv/bin/python backend/test_bridge.py
"""
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    stream=sys.stderr,
)

from mcp_bridge import bridge


async def main() -> None:
    print("=== Step 1: Starting MCP bridge ===")
    await bridge.start()

    print("\n=== Step 2: Listing tools ===")
    tools = await bridge.list_tools()
    print(f"Found {len(tools)} tools:")
    for t in tools:
        print(f"  • {t.name}: {t.description[:80] if t.description else '(no description)'}")

    print("\n=== Step 3: Calling subscription_list ===")
    result = await bridge.call_tool("subscription_list", {})
    print("Result:", result)

    print("\n=== Step 4: Stopping bridge ===")
    await bridge.stop()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
