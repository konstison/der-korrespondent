"""
Der Korrespondent – Generator der Tagesausgabe.

Ablauf:
  1. RSS-Feeds lesen (Politik, Wirtschaft, Wissenschaft, Kultur; deutsch + international)
  2. Chefredaktion: je Ressort ein Thema, echte Meldungen zuordnen, Gewicht vergeben
  3. Volltexte frei zugänglicher Quellen laden (robots.txt wird respektiert)
  4. Essay schreiben – nur auf Basis der Quellen, mit Bezug auf frühere Essays
  5. Faktencheck: zweiter Durchlauf prüft jede Behauptung gegen die Quellen und korrigiert
  6. Englische Fassung
  7. Sonntags zusätzlich: Wochenrückblick aus dem Archiv
  8. Ausgabe + Archiv schreiben (statische Seiten baut scripts/build_site.py)
"""

import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser
import xml.etree.ElementTree as ET
import unicodedata
from datetime import datetime, timedelta
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
# volltext=True: frei zugängliches Angebot, Artikeltext darf geladen werden.
# volltext=False: Bezahl-/Meter-Angebot – nur Titel + Teaser aus dem Feed.
RSS_FEEDS = [
    # --- Nachrichten / Politik: Deutschland
    {"name": "Tagesschau", "land": "Deutschland", "url": "https://www.tagesschau.de/xml/rss2/", "volltext": True},
    {"name": "Deutschlandfunk", "land": "Deutschland", "url": "https://www.deutschlandfunk.de/nachrichten-100.rss", "volltext": True},
    {"name": "FAZ", "land": "Deutschland", "url": "https://www.faz.net/rss/aktuell/", "volltext": False},
    {"name": "Süddeutsche Zeitung", "land": "Deutschland", "url": "https://rss.sueddeutsche.de/rss/Topthemen", "volltext": False},
    {"name": "Die Zeit", "land": "Deutschland", "url": "https://newsfeed.zeit.de/index", "volltext": False},
    {"name": "Der Spiegel", "land": "Deutschland", "url": "https://www.spiegel.de/schlagzeilen/index.rss", "volltext": False},
    # --- Schweiz / Österreich
    {"name": "Neue Zürcher Zeitung", "land": "Schweiz", "url": "https://www.nzz.ch/recent.rss", "volltext": False},
    {"name": "Der Standard", "land": "Österreich", "url": "https://www.derstandard.at/rss", "volltext": True},
    # --- Europa / Welt
    {"name": "Le Monde", "land": "Frankreich", "url": "https://www.lemonde.fr/international/rss_full.xml", "volltext": False},
    {"name": "El País", "land": "Spanien", "url": "https://feeds.elpais.com/mrss-s/pages/ep/site/english.elpais.com/portada", "volltext": False},
    {"name": "Politico Europe", "land": "EU / Brüssel", "url": "https://www.politico.eu/feed/", "volltext": True},
    {"name": "Euronews", "land": "EU / Frankreich", "url": "https://www.euronews.com/rss", "volltext": True},
    {"name": "The Guardian", "land": "Großbritannien", "url": "https://www.theguardian.com/world/rss", "volltext": True},
    {"name": "BBC News", "land": "Großbritannien", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "volltext": True},
    {"name": "The New York Times", "land": "USA", "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "volltext": False},
    {"name": "Al Jazeera", "land": "Katar", "url": "https://www.aljazeera.com/xml/rss/all.xml", "volltext": True},
    # --- Wirtschaft
    {"name": "Tagesschau Wirtschaft", "land": "Deutschland", "url": "https://www.tagesschau.de/wirtschaft/index~rss2.xml", "volltext": True, "anzeige": "Tagesschau"},
    {"name": "FAZ Wirtschaft", "land": "Deutschland", "url": "https://www.faz.net/rss/aktuell/wirtschaft/", "volltext": False, "anzeige": "FAZ"},
    {"name": "Guardian Business", "land": "Großbritannien", "url": "https://www.theguardian.com/business/rss", "volltext": True, "anzeige": "The Guardian"},
    {"name": "BBC Business", "land": "Großbritannien", "url": "https://feeds.bbci.co.uk/news/business/rss.xml", "volltext": True, "anzeige": "BBC News"},
    # --- Wissenschaft, Medizin, Technik
    {"name": "Tagesschau Wissen", "land": "Deutschland", "url": "https://www.tagesschau.de/wissen/index~rss2.xml", "volltext": True, "anzeige": "Tagesschau"},
    {"name": "Spektrum der Wissenschaft", "land": "Deutschland", "url": "https://www.spektrum.de/alias/rss/spektrum-de-rss-feed/996406", "volltext": False},
    {"name": "Deutsches Ärzteblatt", "land": "Deutschland", "url": "https://www.aerzteblatt.de/rss/news.asp", "volltext": False},
    {"name": "Spiegel Wissenschaft", "land": "Deutschland", "url": "https://www.spiegel.de/wissenschaft/index.rss", "volltext": False, "anzeige": "Der Spiegel"},
    {"name": "Guardian Science", "land": "Großbritannien", "url": "https://www.theguardian.com/science/rss", "volltext": True, "anzeige": "The Guardian"},
    {"name": "BBC Science", "land": "Großbritannien", "url": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "volltext": True, "anzeige": "BBC News"},
    {"name": "BBC Technology", "land": "Großbritannien", "url": "https://feeds.bbci.co.uk/news/technology/rss.xml", "volltext": True, "anzeige": "BBC News"},
    {"name": "heise online", "land": "Deutschland", "url": "https://www.heise.de/rss/heise-atom.xml", "volltext": False},
    # --- Kultur / Feuilleton / Gesellschaft
    {"name": "FAZ Feuilleton", "land": "Deutschland", "url": "https://www.faz.net/rss/aktuell/feuilleton/", "volltext": False, "anzeige": "FAZ"},
    {"name": "NZZ Feuilleton", "land": "Schweiz", "url": "https://www.nzz.ch/feuilleton.rss", "volltext": False, "anzeige": "Neue Zürcher Zeitung"},
    {"name": "Spiegel Kultur", "land": "Deutschland", "url": "https://www.spiegel.de/kultur/index.rss", "volltext": False, "anzeige": "Der Spiegel"},
    {"name": "Guardian Culture", "land": "Großbritannien", "url": "https://www.theguardian.com/culture/rss", "volltext": True, "anzeige": "The Guardian"},
]

# Die acht Ressorts der Ausgabe. "standard": Anzahl der Essays, die ohne persönliche Auswahl gezeigt werden.
RESSORTS = [
    {"id": "deutschland", "name": "Deutschland", "hinweis": "Innenpolitik, Bundesregierung, Länder, Gesellschaftspolitik in Deutschland"},
    {"id": "europa", "name": "Europa", "hinweis": "EU, europäische Nachbarn, Schweiz/Österreich, europäische Institutionen"},
    {"id": "welt", "name": "Weltpolitik", "hinweis": "Internationale Beziehungen außerhalb Europas, Großmächte, Diplomatie"},
    {"id": "sicherheit", "name": "Sicherheit & Verteidigung", "hinweis": "Kriege, Konflikte, Militär, Geheimdienste, Rüstungskontrolle"},
    {"id": "wirtschaft", "name": "Wirtschaft", "hinweis": "Konjunktur, Unternehmen, Handel, Finanzen, Energie, Arbeitsmarkt"},
    {"id": "wissenschaft", "name": "Wissenschaft & Medizin", "hinweis": "Forschung, Medizin, Gesundheitswesen, Klima, Umwelt"},
    {"id": "technik", "name": "Technologie & Digitales", "hinweis": "KI, Digitalpolitik, Plattformen, Datenschutz, Raumfahrt"},
    {"id": "feuilleton", "name": "Feuilleton & Gesellschaft", "hinweis": "Kultur, Literatur, Ideen, Medien, Bildung, gesellschaftliche Debatten"},
]
STANDARD_ANZAHL = 5

DEUTSCHSPRACHIG = {"Deutschland", "Schweiz", "Österreich"}
USER_AGENT = "Mozilla/5.0 (compatible; DerKorrespondent/1.2; +https://konstison.github.io/der-korrespondent/)"
VOLLTEXT_MAX_ZEICHEN = 6000
VOLLTEXT_PRO_THEMA = 5

ATOM = "{http://www.w3.org/2005/Atom}"
TAG_RE = re.compile(r"<[^>]+>")


def _text(el):
    return (el.text or "").strip() if el is not None else ""


def _clean(s):
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", s or "")).strip()


def fetch_rss_headlines(limit_per_feed=8):
    print("1. Lese RSS-Feeds...")
    items = []
    for feed in RSS_FEEDS:
        try:
            req = urllib.request.Request(feed["url"], headers={"User-Agent": USER_AGENT})
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
                        "medium": feed.get("anzeige", feed["name"]),
                        "land": feed["land"],
                        "volltext_erlaubt": feed.get("volltext", False),
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
# Volltexte (nur frei zugängliche Quellen, robots.txt wird respektiert)
# ---------------------------------------------------------------------------
_robots_cache = {}


def _robots_erlaubt(url):
    teile = urllib.parse.urlsplit(url)
    basis = f"{teile.scheme}://{teile.netloc}"
    if basis not in _robots_cache:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(basis + "/robots.txt", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as resp:
                rp.parse(resp.read().decode("utf-8", "ignore").splitlines())
        except Exception:
            rp = None  # robots.txt nicht lesbar -> vorsichtshalber kein Volltext
        _robots_cache[basis] = rp
    rp = _robots_cache[basis]
    # Wer Google-Extended (KI-Nutzung durch Google) aussperrt, widerspricht der Verwendung in Gemini –
    # das respektieren wir ebenfalls, zumal Eingaben im Free Tier zur Produktverbesserung genutzt werden.
    return bool(rp and rp.can_fetch(USER_AGENT, url) and rp.can_fetch("Google-Extended", url))


_tdmrep_cache = {}


def _tdm_vorbehalt_domain(url):
    """TDMRep (/.well-known/tdmrep.json): maschinenlesbarer Nutzungsvorbehalt nach § 44b UrhG."""
    teile = urllib.parse.urlsplit(url)
    basis = f"{teile.scheme}://{teile.netloc}"
    if basis not in _tdmrep_cache:
        regeln = []
        try:
            req = urllib.request.Request(basis + "/.well-known/tdmrep.json", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=8) as resp:
                daten = json.loads(resp.read(200_000).decode("utf-8", "ignore"))
            if isinstance(daten, list):
                regeln = [d for d in daten if isinstance(d, dict)]
        except Exception:
            pass
        _tdmrep_cache[basis] = regeln
    pfad = teile.path or "/"
    for r in _tdmrep_cache[basis]:
        ort = str(r.get("location", "/")).rstrip("*")
        if pfad.startswith(ort or "/") and str(r.get("tdm-reservation", "0")) == "1":
            return True
    return False


_TDM_META = re.compile(r'<meta[^>]+name=["\']tdm-reservation["\'][^>]+content=["\']1["\']', re.I)


class _AbsatzParser(HTMLParser):
    """Sammelt den Text aller <p>-Absätze außerhalb von Navigation, Kopf, Fuß, Skripten usw."""
    IGNORIEREN = {"script", "style", "nav", "header", "footer", "aside", "form", "figure", "noscript", "button"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tiefe_ignoriert = 0
        self.in_p = False
        self.absatz = []
        self.absaetze = []

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORIEREN:
            self.tiefe_ignoriert += 1
        elif tag == "p" and not self.tiefe_ignoriert:
            self.in_p, self.absatz = True, []

    def handle_endtag(self, tag):
        if tag in self.IGNORIEREN and self.tiefe_ignoriert:
            self.tiefe_ignoriert -= 1
        elif tag == "p" and self.in_p:
            self.in_p = False
            text = re.sub(r"\s+", " ", "".join(self.absatz)).strip()
            if len(text) > 60:  # kurze Bildunterschriften, Teaser-Fetzen etc. weglassen
                self.absaetze.append(text)

    def handle_data(self, data):
        if self.in_p and not self.tiefe_ignoriert:
            self.absatz.append(data)


def fetch_volltext(url):
    """Lädt den Artikeltext nur, wenn weder robots.txt noch ein TDM-Nutzungsvorbehalt dagegen sprechen."""
    if not _robots_erlaubt(url) or _tdm_vorbehalt_domain(url):
        return ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "de,en;q=0.8"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            if str(resp.headers.get("tdm-reservation", "")).strip() == "1":
                return ""
            charset = resp.headers.get_content_charset() or "utf-8"
            html = resp.read(2_000_000).decode(charset, "ignore")
        if _TDM_META.search(html):
            return ""
        parser = _AbsatzParser()
        parser.feed(html)
        text = "\n".join(parser.absaetze)
        return text[:VOLLTEXT_MAX_ZEICHEN] if len(text) > 400 else ""
    except Exception as ex:
        print(f"   Volltext nicht ladbar ({urllib.parse.urlsplit(url).netloc}): {ex}")
        return ""


def anreichern(sources):
    """Lädt Volltexte für bis zu VOLLTEXT_PRO_THEMA freie Quellen eines Themas."""
    geladen = 0
    for s in sources:
        if geladen >= VOLLTEXT_PRO_THEMA:
            break
        if s.get("volltext_erlaubt") and "volltext" not in s:
            s["volltext"] = fetch_volltext(s["url"])
            if s["volltext"]:
                geladen += 1
    return geladen


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Zwei Tarife: "frei" (Projekt ohne Abrechnung) zuerst, "bezahlt" als Sicherheitsnetz.
#   - Tageskontingent im Free Tier erschöpft  -> Rest des Laufs über den bezahlten Schlüssel
#   - Free Tier überlastet (503) mehrfach      -> diese Anfrage über den bezahlten Schlüssel
#   - Nur ein Schlüssel vorhanden              -> wie bisher, notfalls Ausweichen auf Flash-Lite
# SCHLUESSEL=bezahlt oder =frei erzwingt einen Tarif.
# ---------------------------------------------------------------------------
_clients = {}


def _verfuegbare_tarife():
    modus = os.environ.get("SCHLUESSEL", "automatisch").strip().lower()
    tarife = []
    if modus in ("automatisch", "frei", "") and os.environ.get("GEMINI_API_KEY_FREE"):
        tarife.append("frei")
    if modus in ("automatisch", "bezahlt", "") and os.environ.get("GEMINI_API_KEY"):
        tarife.append("bezahlt")
    if not tarife and os.environ.get("GEMINI_API_KEY"):  # Fallback: irgendein Schlüssel
        tarife.append("bezahlt")
    return tarife


TARIFE = _verfuegbare_tarife()
FREI_GESPERRT = False   # Tageskontingent im Free Tier aufgebraucht


def _gemini(tarif):
    if tarif not in _clients:
        from google import genai
        key = os.environ.get("GEMINI_API_KEY_FREE" if tarif == "frei" else "GEMINI_API_KEY")
        _clients[tarif] = genai.Client(api_key=key)
    return _clients[tarif]


# Modelle je Aufgabe. Die "leichte" Stufe hat im Free Tier ein eigenes, viel größeres Tageskontingent.
MODELL_HAUPT = MODEL_NAME
MODELL_LEICHT = os.environ.get("GEMINI_MODEL_LEICHT", "gemini-3.5-flash-lite")
AUFGABEN_MODELL = {
    "chefredaktion": MODELL_HAUPT,
    "essay": MODELL_HAUPT,
    "faktencheck": os.environ.get("GEMINI_MODEL_FAKTENCHECK", MODELL_HAUPT),
    "uebersetzung": os.environ.get("GEMINI_MODEL_UEBERSETZUNG", MODELL_LEICHT),
}
# Listenpreise in USD pro 1 Mio. Tokens (Eingabe, Ausgabe inkl. Thinking) – nur für die Kostenschätzung im Log
PREISE = {
    "gemini-3.8-flash": (0.375, 1.875),
    "gemini-3.5-flash-lite": (0.10, 0.40),
}
NUTZUNG = {}            # "tarif/modell" -> {"anfragen", "eingabe", "ausgabe", "thinking"}
ERSCHOEPFT = set()      # Modelle, deren Free-Tier-Tageskontingent erschöpft ist (nur ohne bezahlten Schlüssel relevant)


def _buche(tarif, modell, resp):
    u = getattr(resp, "usage_metadata", None)
    n = NUTZUNG.setdefault(f"{tarif}/{modell}", {"anfragen": 0, "eingabe": 0, "ausgabe": 0, "thinking": 0})
    n["anfragen"] += 1
    if u:
        n["eingabe"] += getattr(u, "prompt_token_count", 0) or 0
        n["ausgabe"] += getattr(u, "candidates_token_count", 0) or 0
        n["thinking"] += getattr(u, "thoughts_token_count", 0) or 0


def _tageskontingent_erschoepft(msg):
    m = msg.lower()
    return "429" in m and ("perday" in m or "per day" in m or "requests_per_day" in m or "daily" in m
                           or "free_tier" in m or "freetier" in m)


def _ueberlastet(msg):
    """Vorübergehende Störungen: Überlastung, Serverfehler, abgebrochene oder hängende Verbindungen."""
    m = msg.lower()
    return any(k in m for k in (
        "503", "500", "502", "504", "unavailable", "internal", "overloaded", "high demand",
        "disconnected", "timed out", "timeout", "connection", "remoteprotocolerror", "reset by peer",
        "broken pipe", "eof occurred", "temporarily",
    ))


def call_gemini_json(prompt, versuche=5, aufgabe="essay"):
    """Ruft Gemini mit JSON-Antwort auf und parst das JSON. Bevorzugt den freien Tarif und weicht
    bei erschöpftem Kontingent oder anhaltender Überlastung auf den bezahlten Tarif aus."""
    global FREI_GESPERRT
    from google.genai import types
    config = types.GenerateContentConfig(response_mime_type="application/json")
    if not TARIFE:
        raise RuntimeError("Kein Gemini-API-Schlüssel gesetzt (GEMINI_API_KEY_FREE / GEMINI_API_KEY).")
    last_err = None
    ueberlast_frei = 0
    for attempt in range(1, versuche + 1):
        hat_bezahlt = "bezahlt" in TARIFE
        nutze_frei = "frei" in TARIFE and not FREI_GESPERRT and not (hat_bezahlt and ueberlast_frei >= 2)
        tarif = "frei" if nutze_frei else ("bezahlt" if hat_bezahlt else "frei")
        modell = AUFGABEN_MODELL.get(aufgabe, MODELL_HAUPT)
        if tarif == "frei" and modell in ERSCHOEPFT:
            modell = MODELL_LEICHT
        try:
            resp = _gemini(tarif).models.generate_content(model=modell, contents=prompt, config=config)
            _buche(tarif, modell, resp)
            return json.loads(resp.text)
        except json.JSONDecodeError as ex:
            last_err = ex
            print(f"   Ungültiges JSON (Versuch {attempt}/{versuche}), wiederhole...")
        except Exception as ex:
            last_err = ex
            msg = str(ex)
            print(f"   API-Hinweis [{tarif}/{modell}] (Versuch {attempt}/{versuche}): {msg[:140]}")
            if tarif == "frei" and _tageskontingent_erschoepft(msg):
                if hat_bezahlt:
                    print("   Free-Tier-Kontingent erschöpft – Rest des Laufs über den bezahlten Schlüssel.")
                    FREI_GESPERRT = True
                elif modell != MODELL_LEICHT:
                    print(f"   Tageskontingent von {modell} erschöpft – weiter mit {MODELL_LEICHT}.")
                    ERSCHOEPFT.add(modell)
                else:
                    time.sleep(30)
                continue
            if _ueberlastet(msg) or "429" in msg or "ResourceExhausted" in msg:
                if tarif == "frei":
                    ueberlast_frei += 1
                    if hat_bezahlt and ueberlast_frei >= 2:
                        print("   Free Tier überlastet – diese Anfrage über den bezahlten Schlüssel.")
                        continue
                time.sleep(min(90, attempt * 20))
                continue
            raise
    raise RuntimeError(f"Gemini dauerhaft nicht erreichbar: {last_err}")


def nutzungsbericht(datum):
    """Gibt Anfragen, Tokens und geschätzte Kosten aus und hängt sie an data/nutzung.json an."""
    print("\nNutzung & Kosten (frei = 0 USD; bezahlt zu Listenpreisen geschätzt):")
    gesamt = 0.0
    zeilen = []
    for schluessel, n in NUTZUNG.items():
        tarif, modell = schluessel.split("/", 1)
        p_ein, p_aus = (0, 0) if tarif == "frei" else PREISE.get(modell, (0, 0))
        kosten = n["eingabe"] / 1e6 * p_ein + (n["ausgabe"] + n["thinking"]) / 1e6 * p_aus
        gesamt += kosten
        zeilen.append({"tarif": tarif, "modell": modell, **n, "kosten_usd": round(kosten, 4)})
        print(f"   {tarif:8s} {modell}: {n['anfragen']} Anfragen, {n['eingabe']:,} Eingabe-, {n['ausgabe']:,} Ausgabe-, "
              f"{n['thinking']:,} Thinking-Tokens ≈ {kosten:.3f} USD")
    print(f"   Summe ≈ {gesamt:.3f} USD/Tag ≈ {gesamt * 30:.2f} USD/Monat")
    pfad = os.path.join(DATA_DIR, "nutzung.json")
    try:
        with open(pfad, encoding="utf-8") as f:
            verlauf = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        verlauf = []
    verlauf = [v for v in verlauf if v.get("datum") != datum]
    verlauf.append({"datum": datum, "modelle": zeilen, "summe_usd": round(gesamt, 4)})
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(verlauf[-120:], f, ensure_ascii=False, indent=2)


def pause():
    time.sleep(PAUSE_SEKUNDEN)


PAUSE_SEKUNDEN = int(os.environ.get("PAUSE_SEKUNDEN", "6"))

# ---------------------------------------------------------------------------
# Archiv-Gedächtnis
# ---------------------------------------------------------------------------
def slugify(text, maxlen=70):
    text = text.lower().replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:maxlen].rstrip("-") or "essay"


def artikel_pfad(datum_iso, slug):
    return f"artikel/{datum_iso}/{slug}.html"


def lade_archiv(tage, bis_ausschliesslich):
    """Liefert Essays der letzten `tage` Tage vor dem Stichtag: [{datum, titel, leitthese, schlagworte, pfad}]"""
    essays = []
    for n in range(1, tage + 1):
        d = (bis_ausschliesslich - timedelta(days=n)).strftime("%Y-%m-%d")
        pfad = os.path.join(ARCHIV_DIR, f"{d}.json")
        if not os.path.exists(pfad):
            continue
        try:
            with open(pfad, encoding="utf-8") as f:
                ausgabe = json.load(f)
        except Exception:
            continue
        for a in ausgabe.get("artikel", []):
            slug = a.get("slug") or slugify(a.get("titel", ""))
            essays.append({
                "ref": f"{d}/{slug}",
                "datum": d,
                "ressort": a.get("rubrik", ""),
                "titel": a.get("titel", ""),
                "leitthese": a.get("leitthese", ""),
                "schlagworte": a.get("schlagworte", []),
                "pfad": artikel_pfad(d, slug),
            })
    return essays


# ---------------------------------------------------------------------------
# Chefredaktion: Themenwahl je Ressort
# ---------------------------------------------------------------------------
def choose_topics(items, frueher):
    print("2. Chefredaktion: Themen je Ressort...")
    katalog = [
        {"i": idx, "medium": it["medium"], "land": it["land"], "titel": it["titel"], "kurztext": it["kurztext"][:150]}
        for idx, it in enumerate(items)
    ]
    ressorts = [{"id": r["id"], "name": r["name"], "umfasst": r["hinweis"]} for r in RESSORTS]
    gedaechtnis = [{"ref": e["ref"], "titel": e["titel"], "schlagworte": e["schlagworte"]} for e in frueher]
    prompt = f"""
Du bist Chefredakteur einer anspruchsvollen deutschsprachigen Tageszeitung (Stil: NZZ / FAZ).
Unten stehen die Ressorts, der vollständige Meldungskatalog des heutigen Morgens (jede Meldung mit Index "i")
und die Essays der vergangenen Tage.

AUFGABE: Wähle für JEDES Ressort genau ein Thema für einen analytischen Essay.
- Gewicht und Tragweite vor Aufregung; keine Boulevard-, Promi- oder Sportthemen.
- Jedes Thema muss klar in sein Ressort passen; die acht Themen müssen sich deutlich voneinander unterscheiden.
  Ein Kriegsthema gehört nach "sicherheit", nicht zusätzlich nach "welt" oder "europa".
- Wiederhole kein Thema, das in den letzten Tagen schon einen Essay hatte – es sei denn, es gibt eine
  wesentliche neue Entwicklung. Dann setze "bezug" auf die ref des früheren Essays.
- Ordne jedem Thema ALLE Meldungen zu, die es tatsächlich behandeln (mindestens 2, ideal 4–10),
  wenn möglich auch nicht-deutschsprachige Medien. Nur Indizes, die im Katalog existieren.
- Findet sich für ein Ressort heute kein tragfähiges Thema mit mindestens 2 Meldungen, setze "thema": null.
- "gewicht": 1–10, wie bedeutend das Thema heute für deutschsprachige Leser ist.
- "schlagworte": 2–3 kurze, wiederverwendbare Dossier-Begriffe (z. B. "Ukraine-Krieg", "EU-Asylpolitik",
  "Künstliche Intelligenz"). Verwende dieselben Begriffe wie in früheren Essays, wenn das Thema dasselbe ist.

Antworte als JSON-Objekt:
{{"themen": [{{"ressort": "deutschland", "thema": "Arbeitstitel", "gewicht": 8, "bild_suchbegriff": "englischer Suchbegriff für Wikimedia Commons", "schlagworte": ["..."], "bezug": null, "quellen": [0, 7, 23]}}]}}

Ressorts:
{json.dumps(ressorts, ensure_ascii=False)}

Essays der vergangenen Tage:
{json.dumps(gedaechtnis, ensure_ascii=False)}

Meldungskatalog:
{json.dumps(katalog, ensure_ascii=False)}
"""
    data = call_gemini_json(prompt, aufgabe="chefredaktion")
    themen = data.get("themen", []) if isinstance(data, dict) else data
    gueltig, gesehen = [], set()
    ressort_ids = {r["id"] for r in RESSORTS}
    for t in themen or []:
        if not isinstance(t, dict) or not t.get("thema") or t.get("ressort") not in ressort_ids:
            continue
        if t["ressort"] in gesehen:
            continue
        gesehen.add(t["ressort"])
        gueltig.append(t)
    return gueltig


# ---------------------------------------------------------------------------
# Essay
# ---------------------------------------------------------------------------
def _quellen_fuer_prompt(sources, mit_volltext=True):
    quellen = []
    for n, s in enumerate(sources):
        q = {"q": n, "medium": s["medium"], "land": s["land"], "titel": s["titel"], "kurztext": s["kurztext"]}
        if mit_volltext and s.get("volltext"):
            q["volltext"] = s["volltext"]
        quellen.append(q)
    return quellen


ESSAY_FORMAT = """
Antworte als reines JSON:
{
  "titel": "Klassische Doppelpunkt-Schlagzeile",
  "untertitel": "Sachlicher Untertitel in einem Satz",
  "leitthese": "Zentrale These in 2 Sätzen.",
  "kurzfassung": ["Kernaussage 1", "Kernaussage 2", "Kernaussage 3"],
  "historische_anker": {
    "anker1": {"titel": "...", "text": "Sachliche Erläuterung in 3 Sätzen."},
    "anker2": {"titel": "...", "text": "..."}
  },
  "inhalt_html": "<p>...</p><h2>I. ...</h2><p>...</p>",
  "weltspiegel": [{"q": 0, "tenor": "Analytisch", "zusammenfassung": "2–3 Sätze in eigenen Worten."}]
}
"""

STIL = """
STIL UND INHALT:
- Elegant, präzise, ohne Pathos, ohne Metaphern-Kaskaden, ohne reißerischen Jargon.
- HUMOR: Der Essay bleibt analytisch und auf höchstem sprachlichem Niveau, trägt aber eine feine humoristische
  Note – trockene Ironie, Understatement, die elegant gesetzte Pointe, das treffende Paradox; in der Tradition
  großer Feuilletonisten (Tucholsky, Kästner, Polgar), nie in der des Kabaretts.
  · Ziel des Humors sind das Absurde der Macht, Bürokratie, politische Rhetorik, Widersprüche zwischen Anspruch
    und Wirklichkeit – nie die Opfer, nie das Leid von Menschen, nie Herkunft, Religion oder Körper.
  · Dosierung: etwa eine pointierte Wendung pro Kapitel; lieber eine glänzende als drei mittelmäßige.
    Keine Kalauer, keine Wortspiel-Häufungen, keine Ausrufezeichen, keine flapsige Umgangssprache.
  · Bei Krieg, Terror, Katastrophen, Krankheit und Tod: allenfalls stille Ironie gegenüber Funktionären und
    Phrasen – im Zweifel gar kein Humor. Der Ernst des Themas hat Vorrang.
  · Ironie muss als Ironie erkennbar bleiben und darf keine falschen Tatsachen nahelegen.
- Gliederung: 4 Kapitel mit römischen Überschriften (<h2>I. ...</h2>), dazwischen <p>, optional ein <blockquote>
  (nur als hervorgehobene eigene These, nie als erfundenes Zitat).
- Genau 2 historische oder begriffliche Anker im Text, Format:
  <span class="history-anchor" onclick="showHistory('anker1')">Begriff</span> bzw. 'anker2'.
- "kurzfassung": 3 Sätze, die den Essay für eilige Leser zusammenfassen.
- PERSÖNLICHKEITSRECHTE: Keine herabwürdigenden Etiketten für reale Personen (z. B. „Monster“, „Verbrecher“,
  „Lügner“) – weder in Titel noch Text. Bei Vorwürfen und Verfahren präzise bleiben (beschuldigt, angeklagt,
  nicht rechtskräftig verurteilt, rechtskräftig verurteilt) und die Unschuldsvermutung wahren.
  Kritik richtet sich an Handlungen und Strukturen, nicht an die Würde von Personen.
"""


def write_essay(topic, ressort_name, sources, bezug):
    bezug_text = ""
    if bezug:
        bezug_text = f"""
FRÜHERER ESSAY ZUM THEMA (vom {bezug['datum']}): "{bezug['titel']}" – Leitthese: {bezug['leitthese']}
Knüpfe an diesen Essay an: Was ist seither neu? Erwähne ihn einmal ausdrücklich mit einem Link:
<a href="{bezug['pfad']}">wie wir am {datum_de_kurz(bezug['datum'])} schrieben</a> (Formulierung frei).
"""
    prompt = f"""
Du bist ein erfahrener, nüchterner Autor einer europäischen Qualitätszeitung (Stil: NZZ / FAZ),
Ressort „{ressort_name}“. Schreibe einen tiefgründigen, sachlich fundierten Essay zum Thema: {topic.get('thema')}

UMFANG: mindestens 1.500 Wörter Fließtext (ohne Überschriften). Das ist eine harte Vorgabe.

FAKTENTREUE:
- Aktuelle Fakten (Namen, Zahlen, Ereignisse) NUR aus den beiliegenden Quellen.
  Quellen mit "volltext" sind deine Hauptgrundlage; bei den übrigen kennst du nur Titel und Teaser –
  leite daraus keine Details ab, die dort nicht stehen.
- Erfinde keine Zitate, Zahlen, Personen oder Ämter. Wo die Quellen etwas offen lassen, benenne es als offen.
- Allgemein bekannte historische Tatsachen darfst du zur Einordnung heranziehen.
{STIL}
{bezug_text}
WELTSPIEGEL:
- Wähle 3–4 der beiliegenden Quellen, JEDES MEDIUM HÖCHSTENS EINMAL, und fasse zusammen, wie das jeweilige
  Medium das Thema darstellt. Bevorzuge nicht-deutschsprachige Medien; der Weltspiegel zeigt den Blick von außen.
- Verweise ausschließlich über die Quellennummer "q". Nenne keine anderen Medien und keine URLs.
{ESSAY_FORMAT}
Quellen:
{json.dumps(_quellen_fuer_prompt(sources), ensure_ascii=False)}
"""
    return call_gemini_json(prompt)


def write_glosse(artikel):
    """Kurze tägliche Glosse auf Basis der (bereits faktengeprüften) Essays dieser Ausgabe."""
    material = [{"ressort": a["rubrik"], "titel": a["titel"],
                 "kernaussagen": a.get("kurzfassung") or [a.get("leitthese", "")]} for a in artikel if not a.get("rueckblick")]
    prompt = f"""
Du schreibst „Die Glosse“ einer europäischen Qualitätszeitung – die tägliche kurze Spalte am Ende der Ausgabe,
in der Tradition von Tucholsky, Kästner und Polgar.

AUFGABE: 300–420 Wörter. Nimm EIN Thema des Tages (oder verbinde zwei überraschend) und betrachte es mit
geschliffener Ironie, Understatement und einer Schlusspointe, die nachklingt. Hier darf der Humor die Hauptrolle
spielen – aber auf höchstem sprachlichem Niveau, nie albern, nie zynisch.

REGELN:
- Tatsachen ausschließlich aus dem Material unten; erfinde keine Zitate, Zahlen oder Ereignisse.
- Spott trifft Machtgehabe, Bürokratie, Phrasen, Widersprüche – nie Opfer, nie Leid, nie Herkunft, Religion
  oder Körper. Keine herabwürdigenden Etiketten für reale Personen.
- Kein Thema aus Krieg, Terror, Katastrophen oder Krankheit wählen.
- Form: 3–5 Absätze als <p>, keine Zwischenüberschriften, keine Ausrufezeichen, keine Kalauer.

Antworte als JSON:
{{"titel": "Kurzer, pointierter Titel", "untertitel": "Ein Satz", "inhalt_html": "<p>…</p>"}}

Material (Themen dieser Ausgabe):
{json.dumps(material, ensure_ascii=False)}
"""
    return call_gemini_json(prompt, versuche=3, aufgabe="essay")


def write_wochenrueckblick(woche):
    prompt = f"""
Du bist Chefredakteur einer europäischen Qualitätszeitung (Stil: NZZ / FAZ) und schreibst den
sonntäglichen Wochenrückblick „Die Woche“. Grundlage sind ausschließlich die Essays dieser Woche (unten).

AUFGABE: Kein Nacherzählen der einzelnen Essays, sondern eine übergreifende Deutung:
Welche Linien verbinden die Ereignisse der Woche? Was hat sich verschoben, was bleibt offen?
Mindestens 1.500 Wörter. Verweise auf 4–6 der Essays mit Links im Format <a href="PFAD">…</a>
(PFAD exakt wie angegeben). Keine neuen Fakten, die nicht in den Essays stehen.
{STIL}
Setze "weltspiegel" auf eine leere Liste.
{ESSAY_FORMAT}
Essays der Woche:
{json.dumps(woche, ensure_ascii=False)}
"""
    return call_gemini_json(prompt)


def build_weltspiegel(entries, sources):
    """Verknüpft die Modell-Zusammenfassungen mit den ECHTEN Quelldaten. Ungültige Verweise fallen weg."""
    result, used, medien = [], set(), set()
    for e in entries or []:
        try:
            q = int(e.get("q"))
        except (TypeError, ValueError, AttributeError):
            continue
        if q in used or not (0 <= q < len(sources)):
            continue
        src = sources[q]
        if src["medium"] in medien:
            continue
        used.add(q)
        medien.add(src["medium"])
        result.append({
            "medium": f"{src['medium']}, {src['land']}",
            "tenor": str(e.get("tenor", "")).strip() or "Bericht",
            "zusammenfassung": str(e.get("zusammenfassung", "")).strip(),
            "titel_original": src["titel"],
            "url": src["url"],
            "_international": src["land"] not in DEUTSCHSPRACHIG,
        })
    result.sort(key=lambda r: not r["_international"])
    for r in result:
        del r["_international"]
    return result[:4]


# ---------------------------------------------------------------------------
# Faktencheck
# ---------------------------------------------------------------------------
def faktencheck(essay, sources):
    """Zweiter Durchlauf: prüft konkrete Behauptungen gegen die Quellen und liefert eine korrigierte Fassung."""
    prompt = f"""
Du bist Dokumentar (Faktenprüfer) einer Qualitätszeitung. Prüfe den folgenden Essay gegen die beiliegenden Quellen.

PRÜFE JEDE KONKRETE TATSACHENBEHAUPTUNG zum aktuellen Geschehen: Namen, Ämter, Zahlen, Daten, Orte,
Abläufe, Zitate. Für jede gilt:
- belegt (steht so oder sinngemäß in einer Quelle) → unverändert lassen
- nicht belegt oder widersprüchlich → umformulieren, sodass nur noch das Belegte gesagt wird,
  oder vorsichtig als offen kennzeichnen; erfundene Zitate ganz entfernen
Allgemein bekannte historische Tatsachen und klar erkennbare Deutungen/Meinungen des Autors sind keine Fehler.
Ironische Zuspitzungen, Pointen und Understatement sind Stilmittel, keine Tatsachenbehauptungen: lass sie stehen,
solange sie keine falschen Fakten nahelegen. Entferne Humor nur, wenn er Opfer oder Leid verspottet oder eine
reale Person herabwürdigt.
Prüfe außerdem Titel, Untertitel und Text auf herabwürdigende Etiketten für reale Personen und auf
Formulierungen, die Vorwürfe als erwiesen darstellen, obwohl die Quellen das nicht hergeben – diese entschärfen
und als Korrektur aufführen.
Ändere sonst nichts: Stil, Aufbau, Länge, HTML-Struktur, Links und die history-anchor-Elemente bleiben erhalten.

Antworte als JSON:
{{
  "korrekturen": [{{"stelle": "kurzes Zitat der beanstandeten Stelle", "problem": "warum nicht belegt", "korrektur": "was geändert wurde"}}],
  "titel": "...", "untertitel": "...", "leitthese": "...", "kurzfassung": ["..."],
  "inhalt_html": "vollständiger, korrigierter Essay"
}}
Wenn nichts zu beanstanden ist: "korrekturen": [] und die Felder unverändert zurückgeben.

ESSAY:
{json.dumps({k: essay.get(k) for k in ("titel", "untertitel", "leitthese", "kurzfassung", "inhalt_html")}, ensure_ascii=False)}

QUELLEN:
{json.dumps(_quellen_fuer_prompt(sources), ensure_ascii=False)}
"""
    return call_gemini_json(prompt, versuche=3, aufgabe="faktencheck")


def wende_faktencheck_an(essay, sources):
    woerter_vorher = wortzahl(essay.get("inhalt_html", ""))
    try:
        fc = faktencheck(essay, sources)
    except Exception as ex:
        print(f"   Faktencheck nicht möglich: {ex}")
        return {"geprueft": False}
    korrekturen = [k for k in fc.get("korrekturen", []) if isinstance(k, dict)]
    neu_html = fc.get("inhalt_html", "")
    # Schutz gegen gekürzte oder kaputte Antworten
    if neu_html and wortzahl(neu_html) >= 0.85 * woerter_vorher and "<h2" in neu_html:
        essay["inhalt_html"] = neu_html
        for feld in ("titel", "untertitel", "leitthese"):
            if isinstance(fc.get(feld), str) and fc[feld].strip():
                essay[feld] = fc[feld].strip()
        if isinstance(fc.get("kurzfassung"), list) and fc["kurzfassung"]:
            essay["kurzfassung"] = fc["kurzfassung"]
    elif korrekturen:
        print("   Korrigierte Fassung unbrauchbar (zu kurz) – Original bleibt, Essay als ungeprüft markiert.")
        return {"geprueft": False}
    print(f"   Faktencheck: {len(korrekturen)} Korrektur(en)")
    return {
        "geprueft": True,
        "quellen": len(sources),
        "korrekturen": [
            {"stelle": str(k.get("stelle", ""))[:200], "problem": str(k.get("problem", ""))[:300],
             "korrektur": str(k.get("korrektur", ""))[:300]}
            for k in korrekturen
        ],
    }


# ---------------------------------------------------------------------------
# Englische Fassung
# ---------------------------------------------------------------------------
def uebersetze(artikel):
    payload = {
        "titel": artikel["titel"], "untertitel": artikel["untertitel"], "leitthese": artikel["leitthese"],
        "kurzfassung": artikel.get("kurzfassung", []), "rubrik": artikel["rubrik"],
        "historische_anker": artikel.get("historische_anker", {}),
        "inhalt_html": artikel["inhalt_html"],
        "weltspiegel": [{"tenor": w["tenor"], "zusammenfassung": w["zusammenfassung"]} for w in artikel["weltspiegel"]],
    }
    prompt = f"""
Translate the following German newspaper essay into polished British English, in the register of
The Economist or the Financial Times. Preserve the dry irony and the punchlines – render them as
wittily in English as they are in German, not literally. Keep all HTML tags, attributes, links and the history-anchor
elements exactly as they are (translate only the visible text). Keep the JSON structure and keys
unchanged (keys stay in German); "weltspiegel" keeps the same order and length.

{json.dumps(payload, ensure_ascii=False)}
"""
    en = call_gemini_json(prompt, versuche=3, aufgabe="uebersetzung")
    if not isinstance(en, dict) or wortzahl(en.get("inhalt_html", "")) < 0.7 * artikel.get("woerter", 0):
        raise ValueError("Übersetzung unvollständig")
    ws = en.get("weltspiegel") or []
    return {
        "rubrik": en.get("rubrik", artikel["rubrik"]),
        "titel": en.get("titel", ""), "untertitel": en.get("untertitel", ""), "leitthese": en.get("leitthese", ""),
        "kurzfassung": en.get("kurzfassung", []),
        "historische_anker": en.get("historische_anker", {}),
        "inhalt_html": en.get("inhalt_html", ""),
        "weltspiegel": [
            {"tenor": (ws[i] or {}).get("tenor", w["tenor"]) if i < len(ws) else w["tenor"],
             "zusammenfassung": (ws[i] or {}).get("zusammenfassung", w["zusammenfassung"]) if i < len(ws) else w["zusammenfassung"]}
            for i, w in enumerate(artikel["weltspiegel"])
        ],
    }


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
        req = urllib.request.Request(api_url, headers={"User-Agent": USER_AGENT})
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
    return None


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------
WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]


def datum_de(d):
    return f"{WOCHENTAGE[d.weekday()]}, {d.day}. {MONATE[d.month - 1]} {d.year}"


def datum_de_kurz(iso):
    d = datetime.strptime(iso, "%Y-%m-%d")
    return f"{d.day}. {MONATE[d.month - 1]}"


def wortzahl(html):
    return len(_clean(html).split())


def lesezeit(woerter):
    return max(1, math.ceil(woerter / WOERTER_PRO_MINUTE))


def eindeutiger_slug(titel, vergeben):
    basis = slugify(titel.split(":")[0] if len(titel.split(":")[0]) > 12 else titel)
    slug, n = basis, 2
    while slug in vergeben:
        slug, n = f"{basis}-{n}", n + 1
    vergeben.add(slug)
    return slug


def update_archiv_index(heute, ausgabe):
    pfad = os.path.join(ARCHIV_DIR, "index.json")
    try:
        with open(pfad, encoding="utf-8") as f:
            index = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        index = []
    bekannte = {e["datei"] for e in index}
    for name in sorted(os.listdir(ARCHIV_DIR)):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", name) and name not in bekannte:
            try:
                with open(os.path.join(ARCHIV_DIR, name), encoding="utf-8") as f:
                    index.append(_index_eintrag(name, json.load(f)))
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
def erstelle_artikel(essay, *, nr, ressort_id, ressort_name, gewicht, sources, schlagworte, bild, slugs, ist_rueckblick=False):
    html = essay.get("inhalt_html", "")
    woerter = wortzahl(html)
    titel = essay.get("titel") or ""
    return {
        "id": f"essay-{nr}",
        "slug": eindeutiger_slug(titel, slugs),
        "ressort": ressort_id,
        "rubrik": ressort_name,
        "gewicht": gewicht,
        "standard": False,
        "rueckblick": ist_rueckblick,
        "schlagworte": [str(s).strip() for s in (schlagworte or []) if str(s).strip()][:3],
        "woerter": woerter,
        "lesezeit": f"{lesezeit(woerter)} Min. Lesezeit",
        "titel": titel,
        "untertitel": essay.get("untertitel", ""),
        "leitthese": essay.get("leitthese", ""),
        "kurzfassung": [str(k) for k in (essay.get("kurzfassung") or [])][:3],
        "bild": bild,
        "historische_anker": essay.get("historische_anker", {}),
        "inhalt_html": html,
        "weltspiegel": build_weltspiegel(essay.get("weltspiegel"), sources) if sources else [],
        "quellen": [{"medium": s["medium"], "land": s["land"], "titel": s["titel"], "url": s["url"],
                     "volltext": bool(s.get("volltext"))} for s in sources],
    }


def main():
    jetzt = datetime.now(TZ)
    heute = jetzt.strftime("%Y-%m-%d")
    # MODUS=kompakt (Standard): 5 Essays auf Deutsch + Glosse – passt bequem ins Gratis-Kontingent.
    # MODUS=advanced: alle 8 Ressorts, englische Fassung, Ressortwahl für Leser.
    modus = os.environ.get("MODUS", "kompakt").strip().lower() or "kompakt"
    advanced = modus == "advanced"
    mit_englisch = os.environ.get("ENGLISCH", "1" if advanced else "0") != "0"
    mit_glosse = os.environ.get("GLOSSE", "1") != "0"
    print(f"Modus: {'Advanced' if advanced else 'Kompakt'} (Englisch: {'ja' if mit_englisch else 'nein'}, Glosse: {'ja' if mit_glosse else 'nein'})")

    # Zweiter Versuch am Morgen: nur arbeiten, wenn die heutige Ausgabe noch fehlt
    if os.environ.get("NUR_WENN_FEHLT") == "1" and os.path.exists(os.path.join(ARCHIV_DIR, f"{heute}.json")):
        print("Heutige Ausgabe existiert bereits – nichts zu tun.")
        return

    items = fetch_rss_headlines()
    if len(items) < 20:
        sys.exit("Zu wenige Meldungen – Ausgabe wird nicht erzeugt (alte Ausgabe bleibt bestehen).")

    frueher = lade_archiv(14, jetzt.replace(tzinfo=None))
    frueher_nach_ref = {e["ref"]: e for e in frueher}
    themen = choose_topics(items, frueher)
    ressort_name = {r["id"]: r["name"] for r in RESSORTS}
    reihenfolge = {r["id"]: n for n, r in enumerate(RESSORTS)}
    if not advanced:
        # Die Chefredaktion bewertet weiterhin alle Ressorts; geschrieben werden nur die gewichtigsten Themen.
        def _gewicht(t):
            try:
                return float(t.get("gewicht", 0))
            except (TypeError, ValueError):
                return 0.0
        themen = sorted(themen, key=_gewicht, reverse=True)  # Rest dient als Reserve, falls ein Essay ausfällt
        ziel = STANDARD_ANZAHL
    else:
        themen.sort(key=lambda t: reihenfolge[t["ressort"]])
        ziel = len(themen)
    print(f"   {len(themen)} Themen: " + "; ".join(f"{t['ressort']}: {t['thema']}" for t in themen))
    pause()

    artikel, slugs = [], set()
    for nr, topic in enumerate(themen, start=1):
        if len(artikel) >= ziel:
            break
        if nr > ziel:
            print("   (Reserve-Thema, weil ein Essay ausgefallen ist)")
        rid = topic["ressort"]
        print(f"3. [{ressort_name[rid]}] {topic.get('thema')}")
        idx = [i for i in topic.get("quellen", []) if isinstance(i, int) and 0 <= i < len(items)]
        sources = [items[i] for i in dict.fromkeys(idx)]
        if len(sources) < 2:
            print("   Zu wenige gültige Quellen – übersprungen.")
            continue
        n_voll = anreichern(sources)
        print(f"   {len(sources)} Quellen, davon {n_voll} mit Volltext")
        bezug = frueher_nach_ref.get(topic.get("bezug") or "")
        try:
            essay = write_essay(topic, ressort_name[rid], sources, bezug)
        except Exception as ex:
            print(f"   Essay fehlgeschlagen, übersprungen: {ex}")
            continue
        if wortzahl(essay.get("inhalt_html", "")) < 600:
            print("   Essay zu kurz – übersprungen.")
            continue
        pause()
        fc = wende_faktencheck_an(essay, sources)
        pause()
        try:
            gewicht = float(topic.get("gewicht", 5))
        except (TypeError, ValueError):
            gewicht = 5.0
        a = erstelle_artikel(
            essay, nr=nr, ressort_id=rid, ressort_name=ressort_name[rid], gewicht=gewicht, sources=sources,
            schlagworte=topic.get("schlagworte"), bild=fetch_wikimedia_image(topic.get("bild_suchbegriff")), slugs=slugs,
        )
        a["faktencheck"] = fc
        if bezug:
            a["bezug"] = {"titel": bezug["titel"], "datum": bezug["datum"], "pfad": bezug["pfad"]}
        print(f"   {a['woerter']} Wörter, {len(a['weltspiegel'])} Weltspiegel-Stimmen")
        artikel.append(a)

    # Im Kompakt-Modus wieder in Ressort-Reihenfolge bringen
    if not advanced:
        artikel.sort(key=lambda a: reihenfolge.get(a["ressort"], 99))
    mindestens = 4 if advanced else 3
    if len(artikel) < mindestens:
        nutzungsbericht(heute)
        sys.exit(f"Nur {len(artikel)} Essays erzeugt (mindestens {mindestens} nötig) – Ausgabe wird nicht veröffentlicht.")

    # Sonntag: Wochenrückblick aus den Essays Montag–Samstag
    if jetzt.weekday() == 6:
        woche = [{"datum": e["datum"], "ressort": e["ressort"], "titel": e["titel"], "leitthese": e["leitthese"],
                  "pfad": e["pfad"]} for e in lade_archiv(6, jetzt.replace(tzinfo=None))]
        if len(woche) >= 8:
            print("4. Wochenrückblick „Die Woche“...")
            try:
                essay = write_wochenrueckblick(woche)
                if wortzahl(essay.get("inhalt_html", "")) >= 600:
                    a = erstelle_artikel(essay, nr=len(artikel) + 1, ressort_id="woche", ressort_name="Die Woche",
                                         gewicht=11, sources=[], schlagworte=["Wochenrückblick"], bild=None,
                                         slugs=slugs, ist_rueckblick=True)
                    a["faktencheck"] = {"geprueft": False, "hinweis": "Beruht auf den geprüften Essays der Woche"}
                    artikel.insert(0, a)
                pause()
            except Exception as ex:
                print(f"   Wochenrückblick fehlgeschlagen: {ex}")

    # Standardauswahl: die gewichtigsten Essays (Rückblick immer dabei)
    for a in sorted(artikel, key=lambda x: -x["gewicht"])[:STANDARD_ANZAHL]:
        a["standard"] = True
    for n, a in enumerate(artikel, start=1):
        a["id"] = f"essay-{n}"

    # Die Glosse: kurze humoristische Spalte am Ende der Ausgabe (immer sichtbar)
    print("4b. Die Glosse..." if mit_glosse else "4b. Glosse abgeschaltet.")
    try:
        if not mit_glosse:
            raise StopIteration
        g = write_glosse(artikel)
        if wortzahl(g.get("inhalt_html", "")) >= 150:
            a = erstelle_artikel(g, nr=len(artikel) + 1, ressort_id="glosse", ressort_name="Die Glosse",
                                 gewicht=0, sources=[], schlagworte=["Glosse"], bild=None, slugs=slugs)
            a["glosse"] = True
            a["standard"] = True
            a["faktencheck"] = {"geprueft": False, "hinweis": "Beruht auf den geprüften Essays dieser Ausgabe"}
            artikel.append(a)
            print(f"   „{a['titel']}“ ({a['woerter']} Wörter)")
        pause()
    except StopIteration:
        pass
    except Exception as ex:
        print(f"   Glosse fehlgeschlagen: {ex}")
    for n, a in enumerate(artikel, start=1):
        a["id"] = f"essay-{n}"

    if mit_englisch:
        print("5. Englische Fassung...")
        for a in artikel:
            try:
                a["en"] = uebersetze(a)
                print(f"   ✓ {a['slug']}")
            except Exception as ex:
                print(f"   Übersetzung fehlgeschlagen ({a['slug']}): {ex}")
            pause()

    ausgabe = {
        "datum": datum_de(jetzt),
        "datum_iso": heute,
        "ausgabe_nr": str((jetzt.date() - datetime(2026, 1, 1).date()).days + 1),
        "erzeugt": jetzt.isoformat(timespec="minutes"),
        "modell": MODEL_NAME,
        "modelle": sorted(NUTZUNG.keys()),
        "tarife": TARIFE,
        "modus": "advanced" if advanced else "kompakt",
        "ressorts": [{"id": r["id"], "name": r["name"]} for r in RESSORTS],
        "artikel": artikel,
    }

    os.makedirs(ARCHIV_DIR, exist_ok=True)
    for pfad in (os.path.join(DATA_DIR, "ausgabe.json"), os.path.join(ARCHIV_DIR, f"{heute}.json")):
        with open(pfad, "w", encoding="utf-8") as f:
            json.dump(ausgabe, f, ensure_ascii=False, indent=2)
    update_archiv_index(heute, ausgabe)
    nutzungsbericht(heute)
    print(f"Fertig: {len(artikel)} Essays, archiviert unter {ARCHIV_DIR}/{heute}.json")


if __name__ == "__main__":
    main()
