# YARGUCU – Yargı MCP sunucusu

Bu depo, açık kaynak (MIT lisanslı) **yargi-mcp** paketini (Said Sürücü, https://pypi.org/project/yargi-mcp/)
FastMCP Cloud / Prefect Horizon üzerinde çalıştırmak içindir. Kodun kendisi PyPI paketinden kurulur.

- Giriş noktası (entrypoint): `main.py:mcp`
- Bağımlılıklar `requirements.txt` ve `pyproject.toml` içinde sabitlenmiştir (birlikte çalıştığı denenmiş sürümler).
- Ortam değişkeni gerekmez. (İsteğe bağlı anlamsal arama için `OPENROUTER_API_KEY` eklenebilir.)

Araçlar: Yargıtay, Danıştay, istinaf ve yerel mahkeme kararları (Bedesten), UYAP Emsal, Anayasa Mahkemesi,
Uyuşmazlık Mahkemesi, KİK, Rekabet Kurumu, Sayıştay, KVKK, BDDK, BTK, GİB özelgeleri, Sigorta Tahkim.
