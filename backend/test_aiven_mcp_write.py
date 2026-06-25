"""Aiven MCP WRITE smoke test — the gate for the 'agents use MCP for data' pivot.

Confirms three things before we wire any code:
  1. with read_only OFF, the PostgreSQL data tools (aiven_pg_read / aiven_pg_write)
     actually appear,
  2. the AIVEN_MCP_TOKEN has WRITE scope,
  3. exactly how the tools are called (so we know how the agent must invoke them).

It creates a tiny throwaway table `mcp_probe`, inserts a row, reads it back, and
drops it — all via MCP. Not an investigation; runs in a few seconds.

    cd backend
    python test_aiven_mcp_write.py
"""

import anthropic

from app.config import settings


def _ascii(s) -> str:
    return str(s).encode("ascii", "replace").decode()


_PROMPT = (
    "You are connected to the Aiven MCP server (write-enabled). Project: 'baltic-sentinel'. "
    "There is a PostgreSQL service whose host starts with 'baltic-pg' and database 'defaultdb' "
    "(use a service/list tool to find its exact service name if a tool needs it).\n\n"
    "Do these steps IN ORDER and report exactly what each tool call returns:\n"
    "1. Name every PostgreSQL-related tool you have and the EXACT parameters each requires "
    "(especially the read and write SQL tools).\n"
    "2. Run a write: CREATE TABLE IF NOT EXISTS mcp_probe (id int, note text).\n"
    "3. Run a write: INSERT INTO mcp_probe (id, note) VALUES (1, 'hello-from-mcp').\n"
    "4. Run a read: SELECT * FROM mcp_probe.\n"
    "5. Run a write: DROP TABLE mcp_probe.\n"
    "State clearly whether each step SUCCEEDED or FAILED and why."
)


def main() -> None:
    print("=== Aiven MCP WRITE smoke test ===")
    print("MCP URL :", settings.aiven_mcp_url)
    print("Token   :", "present" if settings.aiven_mcp_token else "MISSING",
          f"(length {len(settings.aiven_mcp_token)})\n")
    if not settings.aiven_mcp_token:
        print("No AIVEN_MCP_TOKEN in backend/.env — add it and rerun.")
        return

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=120.0, max_retries=1)
    mcp = [{"type": "url", "name": "aiven", "url": settings.aiven_mcp_url,
            "authorization_token": settings.aiven_mcp_token}]
    messages = [{"role": "user", "content": _PROMPT}]

    try:
        for step in range(8):
            resp = client.beta.messages.create(
                model="claude-sonnet-4-6", max_tokens=2000,
                betas=["mcp-client-2025-11-20"], mcp_servers=mcp,
                tools=[{"type": "mcp_toolset", "mcp_server_name": "aiven"}],
                messages=messages)
            messages.append({"role": "assistant", "content": resp.content})
            for b in resp.content:
                t = getattr(b, "type", None)
                if t == "text":
                    print("TEXT:", _ascii(b.text[:900]), "\n")
                elif t == "mcp_tool_use":
                    print(f"  MCP CALL -> {getattr(b, 'name', '?')}  input={_ascii(getattr(b, 'input', {}))[:200]}")
                elif t == "mcp_tool_result":
                    print(f"  MCP RESULT is_error={getattr(b, 'is_error', None)}: "
                          f"{_ascii(getattr(b, 'content', None))[:300]}")
            if resp.stop_reason == "end_turn":
                break
        print("\nstop_reason:", resp.stop_reason)
    except Exception as e:  # noqa: BLE001
        print("REQUEST ERROR:", _ascii(repr(e)[:600]))


if __name__ == "__main__":
    main()
