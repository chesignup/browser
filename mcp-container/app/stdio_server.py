"""Run the human-browser MCP server over stdio (for local MCP clients like the
Cursor CLI). Reuses the same tools + stateful session as the HTTP server."""
import server  # registers tools on server.mcp

if __name__ == "__main__":
    server.mcp.run()  # stdio transport by default
