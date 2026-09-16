# `visual_grounding` MCP server

A small MCP server that takes a screenshot and a question and asks a VLM
where things are. The creation prompt calls it by the MCP name
`visual-grounding`.

## Install

```bash
pip install "mcp[cli]>=1.0" openai pillow python-dotenv
```

## Configure

Copy `.env.example` to `.env` in this folder and fill in keys for one
provider (`gemini`, `databricks`, or `openai`). `.env` is gitignored.

## Use it — as an MCP server

Add this to your agent's MCP config (e.g. `.mcp.json` at the repo root
for Claude Code):

```jsonc
{
  "mcpServers": {
    "visual-grounding": {
      "type": "stdio",
      "command": "python",
      "args": [
        "extras/research/software_as_env/creation_audit/mcp/screenshot_query_mcp.py"
      ]
    }
  }
}
```

## Use it — as a Python function

```python
from screenshot_query_mcp import visual_grounding
print(visual_grounding("Where is the Save button?", "/path/to/shot.png"))
```
