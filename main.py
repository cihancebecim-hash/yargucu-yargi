"""YARGUCU kendi MCP sunucusu.

- Yargı araçları: PyPI'daki açık kaynak (MIT lisanslı) yargi-mcp paketi (Said Sürücü).
- Resmî Gazete araçları: resmi_gazete.py (resmigazete.gov.tr'den doğrudan).
- Kaynak Motoru: kaynak/ (oran ve tarifelerin doğrulanmış, tarihe bağlı deposu).

Çalıştırma (kendi sunucunuzda):  python main.py   → MCP_HOST:MCP_PORT/MCP_YOL
"""
import os

from mcp_server_main import app
import resmi_gazete
from kaynak import mcp_araclari

resmi_gazete.register(app)
mcp_araclari.register(app)

mcp = app  # FastMCP giriş noktası: main.py:mcp

if __name__ == "__main__":
    app.run(transport="http",
            host=os.environ.get("MCP_HOST", "127.0.0.1"),
            port=int(os.environ.get("MCP_PORT", "8710")),
            path=os.environ.get("MCP_YOL", "/mcp"))
