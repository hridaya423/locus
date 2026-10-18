"""Every public function in omics_agent/mcp_server.py is a registered MCP tool. Union merges have dropped @mcp.tool
lines silently (classify_assays, get_table and browse_datasets, 18 Oct). Run: uv run python scripts/mcp_check.py"""

import asyncio
import inspect

from omics_agent import mcp_server

public = {name for name, f in vars(mcp_server).items() if inspect.isfunction(f) and f.__module__ == mcp_server.__name__ and not name.startswith("_") and name != "main"}
registered = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
assert public <= registered, f"not registered: {sorted(public - registered)}"
print(f"mcp check passed: {len(registered)} tools, every public function registered")
