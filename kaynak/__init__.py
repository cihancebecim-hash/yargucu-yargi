"""YARGUCU Kaynak Motoru.

Hukuki hesaplarda kullanılan oran ve tarifeleri resmî kaynaklardan toplar,
doğrular, yürürlük tarihine bağlı olarak saklar ve MCP araçlarıyla sunar.

Temel kural: sessiz hata yok. Bir değer ya doğrulanmış olarak kullanılır ya da
kullanılmaz ve alarm üretilir; eski veya şüpheli bir değerle sessizce devam edilmez.
"""

__version__ = "1.0.0"
