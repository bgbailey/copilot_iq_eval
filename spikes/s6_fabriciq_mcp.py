"""Spike S6: the Fabric IQ MCP server from our own client - exact tools and argument names (ADR-006)

Connects as a persona over streamable HTTP with the routing header, lists the tools with their
input schemas (the argument names config/contracts.yaml `fabric_iq_mcp` still marks TODO) and,
optionally, calls one tool with arguments you pass after reading the schema.

    uv run python spikes/s6_fabriciq_mcp.py --persona exec
    uv run python spikes/s6_fabriciq_mcp.py --persona exec \\
        --call DiscoverArtifacts --arguments '{"query": "gross revenue"}'

Raw results go to spikes/out/s6/.
"""

import argparse
import asyncio
import json
from typing import Any

from _common import heading, persona_token, save
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ENDPOINT = "https://fabriciq.svc.cloud.microsoft/v1/mcp/fabriciq"
SCOPES = [
    "https://analysis.windows.net/powerbi/api/Item.Read.All",
    "https://analysis.windows.net/powerbi/api/Item.Execute.All",
]
ROUTING_HEADER = {"X-Variants": "Fabric.Routing.FabricIQ.V1"}


async def probe(token: str, call: str | None, arguments: dict[str, Any]) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}", **ROUTING_HEADER}
    result: dict[str, Any] = {}
    async with (
        streamablehttp_client(ENDPOINT, headers=headers) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        initialized = await session.initialize()
        result["server"] = initialized.model_dump(mode="json")
        tools = await session.list_tools()
        result["tools"] = [tool.model_dump(mode="json") for tool in tools.tools]
        if call:
            reply = await session.call_tool(call, arguments)
            result["call"] = {"tool": call, "arguments": arguments, "result": reply.model_dump(mode="json")}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--persona", default="exec")
    parser.add_argument("--call", help="tool to call after listing, for example ExecuteQuery")
    parser.add_argument("--arguments", default="{}", help="JSON arguments for --call")
    args = parser.parse_args()

    token = persona_token(args.persona, SCOPES)
    result = asyncio.run(probe(token, args.call, json.loads(args.arguments)))
    path = save("s6", args.persona, result)

    heading(f"S6 Fabric IQ MCP as {args.persona}: {len(result['tools'])} tools")
    for tool in result["tools"]:
        schema = tool.get("inputSchema") or {}
        required = set(schema.get("required") or [])
        names = [f"{name}{'*' if name in required else ''}" for name in (schema.get("properties") or {})]
        print(f"- {tool['name']}({', '.join(names)})\n  {str(tool.get('description', ''))[:160]}")
    if "call" in result:
        heading(f"{args.call} result")
        print(json.dumps(result["call"]["result"], indent=2)[:3000])
    print(f"\n* = required. For ADR-006 and contracts.yaml execute_query: the argument names above. Raw: {path}")


if __name__ == "__main__":
    main()
