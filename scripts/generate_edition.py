"""
Der Korrespondent – Generator der Tagesausgabe.

Ablauf:
  1. RSS-Feeds aller Quellen lesen (deutsch + international)
  2. Gemini wählt 5 Themen und ordnet jedem Thema echte Meldungen zu
  3. Gemini schreibt je Thema einen Essay – NUR auf Basis der zugeordneten Meldungen
  4. Der Weltspiegel wird im Code aus den echten Meldungen gebaut:
     Medium, Land und URL stammen immer aus dem Feed, nie vom Modell.
  5. Ausgabe nach data/ausgabe.json, Kopie ins Archiv, Archiv-Index aktualisieren
"""

import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo

sys.stdout.reconfigure(line_buffering=True)

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
TZ = ZoneInfo("Europe/Berlin")
DATA_DIR = "data"
ARCHIV_DIR = os.path.join(DATA_DIR, "archiv")
WOERTER_PRO_MINUTE = 220

# ---------------------------------------------------------------------------
# Quellen
# ---------------------------------------------------------------------------
RSS_FEEDS = [
    # Deutschland / DACH
    {"name": "Tagesschau", "land": "Deutschland", "url": "https://www.tagesschau.de/xml/rss2/"},
    {"name": "Deutschlandfunk", "land": "Deutschland", "url": "https://www.deutschlandfunk.de/nachrichten-100.rss"},
    {"name": "FAZ", "land": "Deutschland", "url": "https://www.faz.net/rss/aktuell/"},
    {"name": "Der Spiegel", "land": "Deutschland", "url": "https://www.spiegel.de/schlagzeilen/index.rss"},
    {"name": "Neue Zürcher Zeitung", "land": "Schweiz", "url": "https://www.nzz.ch/recent.rss"},
    {"name": "Der Standard", "land": "Österreich", "url": "https://www.derstandard.at/rss"},
    # International
    {"name": "The Guardian", "land": "Großbritannien", "url": "https://www.theguardian.com/world/rss"},
    {"name": "BBC News", "land": "Großbritannien", "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    {"name": "Le Monde", "land": "Frankreich", "url": "https://www.lemonde.fr/international/rss_full.xml"},
    {"name": "Al Jazeera", "land": "Katar", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
]

ATOM = "{http://www.w3.org/2005/Atom}"
TAG_RE = re.compile(r"<[^>]+>")


def _text(el):
    return (el.text or "").strip() if el is not None else ""


def _clean(s):
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", s or "")).strip()


def fetch_rss_headlines(limit_per_feed=10):
    print("1. Lese RSS-Feeds...")
    items = []
    for feed in RSS_FEEDS:
        try:
            req = urllib.request.Request(feed["url"], headers={"User-Agent": "Mozilla/5.0 (DerKorrespondent)"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                root = ET.fromstring(resp.read())

            entries = root.findall(".//item") or root.findall(f"{ATOM}entry")
            count = 0
            for e in entries:
                if count >= limit_per_feed:
                    break
                title = _clean(_text(e.find("title")) or _text(e.find(f"{ATOM}title")))
                desc = _clean(
                    _text(e.find("description"))
                    or _text(e.find(f"{ATOM}summary"))
                    or _text(e.find(f"{ATOM}content"))
                )
                link = _text(e.find("link"))
                if not link:
                    atom_link = e.find(f"{ATOM}link")
                    link = atom_link.attrib.get("href", "") if atom_link is not None else ""
                if title and link.startswith("http"):
                    items.append({
                        "medium": feed["name"],
                        "land": feed["land"],
                        "titel": title,
                        "kurztext": desc[:400],
                        "url": link.strip(),
                    })
                    count += 1
            print(f"   {feed['name']}: {count}")
        except Exception as ex:
            print(f"   Warnung bei Feed {feed['name']}: {ex}")

    # Dubletten (gleiche URL) entfernen
    seen, unique = set(), []
    for it in items:
        if it["url"] not in seen:
            seen.add(it["url"])
            unique.append(it)
    print(f"-> {len(unique)} Meldungen aus {len({i['medium'] for i in unique})} Medien.")
    return unique


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------
_client = None


def _gemini():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client()
    return _client


def call_gemini_json(prompt):
    """Ruft Gemini mit JSON-Antwort auf; fängt Limits/Überlastung ab und parst das JSON."""
    from google.genai import types
    config = types.GenerateContentConfig(response_mime_type="application/json")
    last_err = None
    for attempt in range(1, 5):
        try:
            resp = _gemini().models.generate_content(model=MODEL_NAME, contents=prompt, config=config)
            return json.loads(resp.text)
        except json.JSONDecodeError as ex:
            last_err = ex
            print(f"   Ungültiges JSON (Versuch {attempt}/4), wiederhole...")
        except Exception as ex:
            last_err = ex
            msg = str(ex)
            print(f"   API-Hinweis (Versuch {attempt}/4): {msg[:150]}")
            if any(k in msg for k in ("429", "503", "500", "ResourceExhausted", "UNAVAILABLE", "INTERNAL")):
                time.sleep(attempt * 20)
                continue
            raise
    raise RuntimeError(f"Gemini dauerhaft nicht erreichbar: {last_err}")


def choose_topics(items):
    print("2. Wähle 5 Themen...")
    katalog = [
        {"i": idx, "medium": it["medium"], "land": it["land"], "titel": it["titel"], "kurztext": it["kurztext"][:160]}
        for idx, it in enumerate(items)
    ]
    prompt = f"""
Du bist Chefredakteur einer anspruchsvollen deutschsprachigen Tageszeitung (Stil: NZZ / FAZ).
Unten steht der vollständige Meldungskatalog des heutigen Morgens, jede Meldung mit Index "i".

Wähle exakt 5 Themen, die für den deutschsprachigen Leserraum heute am bedeutendsten sind.
Kriterien:
- Gewicht und Tragweite vor Aufregung; keine Boulevard- oder Sportthemen.
- Bevorzuge Themen, über die mehrere Medien aus verschiedenen Ländern berichten.
- Die 5 Themen sollen sich inhaltlich klar unterscheiden.
- Ordne jedem Thema ALLE Meldungen aus dem Katalog zu, die es tatsächlich behandeln (mindestens 2, ideal 3–8).
  Verwende nur Indizes, die im Katalog existieren.

Antworte als JSON-Array mit 5 Objekten:
[{{"rubrik": "Geopolitik & Europa", "arbeitstitel": "...", "bild_suchbegriff": "englischer Suchbegriff für Wikimedia Commons", "quellen": [0, 7, 23]}}]

Meldungskatalog:
{json.dumps(katalog, ensure_ascii=False)}
"""
    topics = call_gemini_json(prompt)
    if isinstance(topics, dict):  # manche Modelle verpacken das Array
        topics = next((v for v in topics.values() if isinstance(v, list)), [])
    return topics[:5]


def write_essay(topic, sources):
    quellen = [
        {"q": n, "medium": s["medium"], "land": s["land"], "titel": s["titel"], "kurztext": s["kurztext"]}
        for n, s in enumerate(sources)
    ]
    prompt = f"""
Du bist ein erfahrener, nüchterner Leitartikler einer europäischen Qualitätszeitung (Stil: NZZ / FAZ).
Schreibe einen tiefgründigen, sachlich fundierten Essay zum Thema: {topic.get('arbeitstitel')}

UMFANG: mindestens 1.500 Wörter Fließtext (ohne Überschriften). Das ist eine harte Vorgabe.

STIL UND INHALT:
- Elegant, präzise, ohne Pathos, ohne Metaphern-Kaskaden, ohne reißerischen Jargon.
- Faktentreue: Aktuelle Fakten (Namen, Zahlen, Ereignisse von heute) NUR aus den beiliegenden Quellen.
  Erfinde keine Zitate, Zahlen, Personen oder Ämter. Wo die Quellen etwas offen lassen, benenne es als offen.
- Allgemein bekannte historische Tatsachen darfst du zur Einordnung heranziehen.
- Gliederung: 4 Kapitel mit römischen Überschriften (<h2>I. ...</h2>), dazwischen <p>, optional ein <blockquote>
  (nur als hervorgehobene eigene These, nicht als erfundenes Zitat).
- Genau 2 historische oder begriffliche Anker im Text, Format:
  <span class="history-anchor" onclick="showHistory('anker1')">Begriff</span> bzw. 'anker2'.

WELTSPIEGEL:
- Fasse für 2–4 der beiliegenden Quellen (bevorzugt aus verschiedenen Ländern) zusammen, wie das jeweilige Medium
  das Thema darstellt. Verweise ausschließlich über die Quellennummer "q". Nenne keine anderen Medien und keine URLs.

Antworte als reines JSON:
{{
  "titel": "Klassische Doppelpunkt-Schlagzeile",
  "untertitel": "Sachlicher Untertitel in einem Satz",
  "leitthese": "Zentrale These in 2 Sätzen.",
  "historische_anker": {{
    "anker1": {{"titel": "...", "text": "Sachliche Erläuterung in 3 Sätzen."}},
    "anker2": {{"titel": "...", "text": "..."}}
  }},
  "inhalt_html": "<p>...</p><h2>I. ...</h2><p>...</p>",
  "weltspiegel": [{{"q": 0, "tenor": "Analytisch", "zusammenfassung": "2–3 Sätze in eigenen Worten."}}]
}}

Quellen:
{json.dumps(quellen, ensure_ascii=False)}
"""
    return call_gemini_json(prompt)


def build_weltspiegel(entries, sources):
    """Verknüpft die Modell-Zusammenfassungen mit den ECHTEN Quelldaten. Ungültige Verweise fallen weg."""
    result, used = [], set()
    for e in entries or []:
        try:
            q = int(e.get("q"))
        except (TypeError, ValueError):
            continue
        if q in used or not (0 <= q < len(sources)):
            continue
        used.add(q)
        src = sources[q]
        result.append({
            "medium": f"{src['medium']}, {src['land']}",
            "tenor": str(e.get("tenor", "")).strip() or "Bericht",
            "zusammenfassung": str(e.get("zusammenfassung", "")).strip(),
            "titel_original": src["titel"],
            "url": src["url"],
        })
    return result


# ---------------------------------------------------------------------------
# Bilder (Wikimedia Commons)
# ---------------------------------------------------------------------------
def fetch_wikimedia_image(query):
    if not query:
        return None
    try:
        api_url = (
            "https://commons.wikimedia.org/w/api.php?action=query&generator=search"
            f"&gsrsearch=filetype:bitmap+{urllib.parse.quote(query)}&gsrnamespace=6&gsrlimit=1"
            "&prop=imageinfo&iiprop=url|extmetadata&iiurlwidth=1280&format=json"
        )
        req = urllib.request.Request(api_url, headers={"User-Agent": "DerKorrespondent/1.1"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for page in data.get("query", {}).get("pages", {}).values():
            info = page.get("imageinfo", [{}])[0]
            meta = info.get("extmetadata", {})
            if info.get("thumburl"):
                autor = _clean(meta.get("Artist", {}).get("value", ""))[:80]
                lizenz = _clean(meta.get("LicenseShortName", {}).get("value", ""))
                credit = " · ".join(x for x in (autor, lizenz) if x)
                return {
                    "url": info["thumburl"],
                    "beschreibung": _clean(meta.get("ImageDescription", {}).get("value", ""))[:160] or query,
                    "lizenz": f"Foto: {credit} (Wikimedia Commons)" if credit else "Foto: Wikimedia Commons",
                    "quelle": info.get("descriptionurl", ""),
                }
    except Exception as ex:
        print(f"   Bildsuche-Fehler: {ex}")
    return None  # Frontend zeigt dann einfach kein Bild


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------
WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]


def datum_de(d):
    return f"{WOCHENTAGE[d.weekday()]}, {d.day}. {MONATE[d.month - 1]} {d.year}"


def wortzahl(html):
    return len(_clean(html).split())


def update_archiv_index(heute, ausgabe):
    pfad = os.path.join(ARCHIV_DIR, "index.json")
    try:
        with open(pfad, encoding="utf-8") as f:
            index = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        index = []

    # Einträge für vorhandene Archivdateien ergänzen, die (noch) nicht im Index stehen
    bekannte = {e["datei"] for e in index}
    for name in sorted(os.listdir(ARCHIV_DIR)):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", name) and name not in bekannte:
            try:
                with open(os.path.join(ARCHIV_DIR, name), encoding="utf-8") as f:
                    a = json.load(f)
                index.append(_index_eintrag(name, a))
            except Exception:
                pass

    index = [e for e in index if e["datei"] != f"{heute}.json"]
    index.append(_index_eintrag(f"{heute}.json", ausgabe))
    index.sort(key=lambda e: e["datei"], reverse=True)
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def _index_eintrag(datei, ausgabe):
    return {
        "datei": datei,
        "datum": ausgabe.get("datum", datei[:10]),
        "ausgabe_nr": ausgabe.get("ausgabe_nr", ""),
        "titel": [a.get("titel", "") for a in ausgabe.get("artikel", [])],
    }


# ---------------------------------------------------------------------------
# Hauptprogramm
# ---------------------------------------------------------------------------
def main():
    jetzt = datetime.now(TZ)
    heute = jetzt.strftime("%Y-%m-%d")

    items = fetch_rss_headlines()
    if len(items) < 10:
        sys.exit("Zu wenige Meldungen – Ausgabe wird nicht erzeugt (alte Ausgabe bleibt bestehen).")

    topics = choose_topics(items)
    artikel = []
    for nr, topic in enumerate(topics, start=1):
        print(f"3. Essay {nr}/{len(topics)}: {topic.get('arbeitstitel')}")
        idx = [i for i in topic.get("quellen", []) if isinstance(i, int) and 0 <= i < len(items)]
        sources = [items[i] for i in dict.fromkeys(idx)]
        if len(sources) < 1:
            print("   Keine gültigen Quellen – Thema übersprungen.")
            continue
        try:
            essay = write_essay(topic, sources)
        except Exception as ex:
            print(f"   Essay fehlgeschlagen, übersprungen: {ex}")
            continue

        html = essay.get("inhalt_html", "")
        woerter = wortzahl(html)
        if woerter < 300:
            print(f"   Essay zu kurz ({woerter} Wörter) – übersprungen.")
            continue
        print(f"   {woerter} Wörter, {len(sources)} Quellen")

        artikel.append({
            "id": f"essay-{nr}",
            "rubrik": topic.get("rubrik", "Zeitgeschehen"),
            "woerter": woerter,
            "lesezeit": f"{max(1, math.ceil(woerter / WOERTER_PRO_MINUTE))} Min. Lesezeit",
            "titel": essay.get("titel") or topic.get("arbeitstitel", ""),
            "untertitel": essay.get("untertitel", ""),
            "leitthese": essay.get("leitthese", ""),
            "bild": fetch_wikimedia_image(topic.get("bild_suchbegriff")),
            "historische_anker": essay.get("historische_anker", {}),
            "inhalt_html": html,
            "weltspiegel": build_weltspiegel(essay.get("weltspiegel"), sources),
            "quellen": [{"medium": s["medium"], "land": s["land"], "titel": s["titel"], "url": s["url"]} for s in sources],
        })
        time.sleep(8)

    if len(artikel) < 3:
        sys.exit(f"Nur {len(artikel)} Essays erzeugt – Ausgabe wird nicht veröffentlicht.")

    ausgabe = {
        "datum": datum_de(jetzt),
        "datum_iso": heute,
        "ausgabe_nr": str((jetzt.date() - datetime(2026, 1, 1).date()).days + 1),
        "erzeugt": jetzt.isoformat(timespec="minutes"),
        "modell": MODEL_NAME,
        "artikel": artikel,
    }

    os.makedirs(ARCHIV_DIR, exist_ok=True)
    for pfad in (os.path.join(DATA_DIR, "ausgabe.json"), os.path.join(ARCHIV_DIR, f"{heute}.json")):
        with open(pfad, "w", encoding="utf-8") as f:
            json.dump(ausgabe, f, ensure_ascii=False, indent=2)
    update_archiv_index(heute, ausgabe)
    print(f"Fertig: {len(artikel)} Essays, archiviert unter {ARCHIV_DIR}/{heute}.json")


if __name__ == "__main__":
    main()
