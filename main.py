"""YARGUCU için Yargı MCP sunucusu.

Kod, PyPI'daki açık kaynak (MIT lisanslı) yargi-mcp paketinden gelir:
https://pypi.org/project/yargi-mcp/  (Said Sürücü)
Bu dosya paketteki FastMCP sunucusunu bulut dağıtımı için dışarı açar ve
YARGUCU'ya özgü Resmî Gazete araçlarını (resmi_gazete.py) ekler.
"""
from mcp_server_main import app
import resmi_gazete

resmi_gazete.register(app)

mcp = app  # FastMCP Cloud / Horizon giriş noktası: main.py:mcp

if __name__ == "__main__":
    app.run()
