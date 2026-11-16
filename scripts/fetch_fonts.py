"""
Lädt die Schriften (Cormorant Garamond, Newsreader, Inter) einmalig von Google Fonts herunter
und legt sie unter assets/fonts/ ab. Danach werden keine Daten mehr an Google übertragen (DSGVO).
Wird über den Workflow „Schriften lokal einbinden“ ausgeführt.
"""
import os
import re
import urllib.request

CSS_URL = ("https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;0,600;0,700;1,400;1,600"
           "&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;1,6..72,400"
           "&family=Inter:wght@400;500;600&display=swap")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
SUBSETS = {"latin", "latin-ext"}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
        return r.read()


css = get(CSS_URL).decode("utf-8")
blocks = re.findall(r"/\*\s*([\w-]+)\s*\*/\s*(@font-face\s*{[^}]*})", css)
os.makedirs("assets/fonts", exist_ok=True)
out, n = [], 0
for subset, block in blocks:
    if subset not in SUBSETS:
        continue
    url = re.search(r"url\((https://[^)]+\.woff2)\)", block).group(1)
    family = re.search(r"font-family:\s*'([^']+)'", block).group(1)
    style = re.search(r"font-style:\s*(\w+)", block).group(1)
    weight = re.search(r"font-weight:\s*([\d ]+)", block).group(1).strip().replace(" ", "-")
    name = f"{family.lower().replace(' ', '-')}-{style}-{weight}-{subset}.woff2"
    path = f"assets/fonts/{name}"
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(get(url))
        n += 1
    out.append(f"/* {subset} */\n" + block.replace(url, f"fonts/{name}"))
with open("assets/fonts.css", "w", encoding="utf-8") as f:
    f.write("/* Lokal eingebundene Schriften (SIL Open Font License) */\n" + "\n".join(out) + "\n")
print(f"{len(out)} @font-face-Regeln, {n} Dateien geladen.")
