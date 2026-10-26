"""YARGUCU için Yargı MCP sunucusu.

Kod, PyPI'daki açık kaynak (MIT lisanslı) yargi-mcp paketinden gelir:
https://pypi.org/project/yargi-mcp/  (Said Sürücü)
Bu dosya yalnızca paketteki FastMCP sunucusunu bulut dağıtımı için dışarı açar.
"""
from mcp_server_main import app

mcp = app  # FastMCP Cloud / Horizon giriş noktası: main.py:mcp

if __name__ == "__main__":
    app.run()
