"""Standalone Aiven MCP connectivity test.

Run it to check whether the backend can reach + authenticate to the hosted Aiven
MCP server. Useful to show an Aiven mentor exactly what we send and what we get back.

    conda activate st
    cd backend
    python test_aiven_mcp.py

It uses the Anthropic API "MCP connector" (beta) to ask Claude to list the Aiven
MCP tools and call one read-only tool, then prints the raw result.
"""

import anthropic

from app.config import settings


def _ascii(s: str) -> str:
    return str(s).encode("ascii", "replace").decode()


def main() -> None:
    print("=== Aiven MCP test ===")
    print("MCP URL :", settings.aiven_mcp_url)
    print("Token   :", "present" if settings.aiven_mcp_token else "MISSING",
          f"(length {len(settings.aiven_mcp_token)})")
    print("Auth    : sent as HTTP Bearer 'authorization_token' via Anthropic's MCP connector\n")
    if not settings.aiven_mcp_token:
        print("No AIVEN_MCP_TOKEN in backend/.env — add it and rerun.")
        return

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        resp = client.beta.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            betas=["mcp-client-2025-11-20"],
            mcp_servers=[{
                "type": "url", "name": "aiven", "url": settings.aiven_mcp_url,
                "authorization_token": settings.aiven_mcp_token,
            }],
            tools=[{"type": "mcp_toolset", "mcp_server_name": "aiven"}],
            messages=[{"role": "user", "content":
                       "List the Aiven MCP tools available to you, then call ONE read-only "
                       "tool (e.g. list projects) and report exactly what it returns."}],
        )
        print("stop_reason:", resp.stop_reason, "\n")
        for b in resp.content:
            t = getattr(b, "type", None)
            if t == "text":
                print("TEXT:\n", _ascii(b.text[:1200]), "\n")
            elif t == "mcp_tool_use":
                print("MCP TOOL CALLED:", getattr(b, "name", None))
            elif t == "mcp_tool_result":
                print("MCP RESULT  is_error:", getattr(b, "is_error", None))
                print("            content :", _ascii(str(getattr(b, "content", None))[:600]), "\n")
            else:
                print("BLOCK:", t)
    except Exception as e:
        print("REQUEST ERROR:", _ascii(repr(e)[:600]))


if __name__ == "__main__":
    main()
