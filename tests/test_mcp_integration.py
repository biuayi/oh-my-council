import asyncio


def test_server_exposes_three_tools():
    from omc.mcp_server import build_server
    app = build_server()
    tools = asyncio.run(app.list_tools())
    names = {t.name for t in tools}
    assert {"omc_status", "omc_new", "omc_start"} <= names
