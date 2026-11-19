"""
Der Korrespondent – baut die statischen Seiten aus dem Archiv.

Erzeugt (bei jedem Lauf vollständig neu):
  artikel/<datum>/<slug>.html     eine Seite pro Essay (deutsch), mit Vorschaubild-Tags für Messenger/Social Media
  en/<datum>/<slug>.html          englische Fassung, falls vorhanden
  archiv.html                     alle Ausgaben nach Monaten, mit Suche
  themen/index.html, themen/*.html  Dossiers nach Schlagworten
  feed.xml                        RSS-Feed der Essays (z. B. für einen Newsletter-Dienst)
  sitemap.xml, robots.txt         für Suchmaschinen

Die Basis-URL kommt aus der Umgebungsvariable SITE_URL (bei eigener Domain dort ändern).
"""

import html
import json
import os
import re
import shutil
import sys
import unicodedata
from datetime import datetime
from email.utils import format_datetime
from zoneinfo import ZoneInfo

SITE_URL = os.environ.get("SITE_URL", "https://konstison.github.io/der-korrespondent").rstrip("/")
ARCHIV_DIR = os.path.join("data", "archiv")
TZ = ZoneInfo("Europe/Berlin")
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"]
TAG_RE = re.compile(r"<[^>]+>")

esc = lambda s: html.escape(str(s or ""), quote=True)


def slugify(text, maxlen=70):
    text = str(text).lower().replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:maxlen].rstrip("-") or "essay"


def plain(s):
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", s or "")).strip()


def kuerzen(s, n=200):
    s = plain(s)
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


# ---------------------------------------------------------------------------
# Archiv laden
# ---------------------------------------------------------------------------
def lade_alle_essays():
    essays = []
    if not os.path.isdir(ARCHIV_DIR):
        return essays
    for name in sorted(os.listdir(ARCHIV_DIR), reverse=True):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", name):
            continue
        datum = name[:10]
        try:
            with open(os.path.join(ARCHIV_DIR, name), encoding="utf-8") as f:
                ausgabe = json.load(f)
        except Exception as ex:
            print(f"Überspringe {name}: {ex}")
            continue
        slugs = set()
        for a in ausgabe.get("artikel", []):
            slug = a.get("slug") or slugify(a.get("titel", ""))
            while slug in slugs:
                slug += "-2"
            slugs.add(slug)
            essays.append({**a, "_datum": datum, "_slug": slug, "_ausgabe": ausgabe.get("datum", datum),
                           "_nr": ausgabe.get("ausgabe_nr", "")})
    return essays


def pfad_de(e):
    return f"artikel/{e['_datum']}/{e['_slug']}.html"


def pfad_en(e):
    return f"en/{e['_datum']}/{e['_slug']}.html"


def datum_lang(iso, en=False):
    d = datetime.strptime(iso, "%Y-%m-%d")
    return f"{MONTHS_EN[d.month - 1]} {d.day}, {d.year}" if en else f"{d.day}. {MONATE[d.month - 1]} {d.year}"


# ---------------------------------------------------------------------------
# Bausteine
# ---------------------------------------------------------------------------
PREFS_SCRIPT = """<script>
try {
  var t = localStorage.getItem('korrespondent.theme');
  if (t === 'evening') document.documentElement.setAttribute('data-theme', 'evening');
  var s = [0.85, 0.92, 1, 1.1, 1.2, 1.32, 1.45, 1.6][parseInt(localStorage.getItem('korrespondent.textScale'), 10)];
  if (s) document.documentElement.style.setProperty('--text-scale', s);
} catch (e) {}
</script>"""


def kopf(titel, beschreibung, rel, kanonisch, bild=None, typ="website", lang="de", alternate=None):
    og_bild = bild or f"{SITE_URL}/assets/og-image.png"
    alt = ""
    if alternate:
        for hl, url in alternate.items():
            alt += f'\n  <link rel="alternate" hreflang="{hl}" href="{esc(url)}">'
    return f"""<!DOCTYPE html>
<html lang="{lang}" data-theme="day">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc(titel)}</title>
  <meta name="description" content="{esc(beschreibung)}">
  <meta name="ai-generated" content="true">
  <link rel="canonical" href="{esc(kanonisch)}">{alt}
  <meta property="og:site_name" content="Der Korrespondent">
  <meta property="og:type" content="{typ}">
  <meta property="og:title" content="{esc(titel)}">
  <meta property="og:description" content="{esc(beschreibung)}">
  <meta property="og:url" content="{esc(kanonisch)}">
  <meta property="og:image" content="{esc(og_bild)}">
  <meta property="og:locale" content="{'en_GB' if lang == 'en' else 'de_DE'}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="theme-color" content="#1A1917">
  <link rel="icon" type="image/svg+xml" href="{rel}icon.svg">
  <link rel="apple-touch-icon" href="{rel}assets/icon-180.png">
  <link rel="alternate" type="application/rss+xml" title="Der Korrespondent" href="{rel}feed.xml">
  <link rel="stylesheet" href="{rel}assets/fonts.css">
  <link rel="stylesheet" href="{rel}assets/site.css">
  {PREFS_SCRIPT}
</head>
<body>
"""


def leiste(rel, en=False):
    if en:
        links = f'<a href="{rel}index.html?lang=en">Today\'s edition</a><a href="{rel}archiv.html">Archive</a><a href="{rel}themen/index.html">Dossiers</a>'
    else:
        links = f'<a href="{rel}index.html">Heutige Ausgabe</a><a href="{rel}archiv.html">Archiv</a><a href="{rel}themen/index.html">Dossiers</a>'
    return f'<header class="site-bar"><a class="logo" href="{rel}index.html">Der Korrespondent</a><nav>{links}</nav></header>\n'


def fuss(rel, en=False):
    if en:
        text = ("All essays are researched and written with AI assistance on the basis of publicly available news sources, "
                "then fact-checked automatically against those sources. ")
    else:
        text = ("Alle Essays werden auf Basis öffentlich zugänglicher Nachrichtenquellen KI-gestützt recherchiert und verfasst "
                "und anschließend automatisiert gegen diese Quellen geprüft. ")
    return f"""<footer class="site-footer">
  <strong>DER KORRESPONDENT</strong> · München · {text}
  <a href="{rel}index.html#impressum">Impressum &amp; Datenschutz</a> · <a href="{rel}index.html#feedback">Feedback</a> · <a href="{rel}feed.xml">RSS</a>
</footer>
<script>
document.querySelectorAll('.history-anchor').forEach(function (el) {{
  var m = (el.getAttribute('onclick') || '').match(/showHistory\\('([^']+)'\\)/);
  el.removeAttribute('onclick');
  if (m && window.ANKER && ANKER[m[1]]) el.title = ANKER[m[1]].titel + ': ' + ANKER[m[1]].text;
}});
</script>
</body>
</html>
"""


def links_umschreiben(inhalt, rel):
    """Interne Links im Essay (artikel/…) relativ zur aktuellen Seite machen."""
    return re.sub(r'href="(artikel/[^"]+)"', lambda m: f'href="{rel}{m.group(1)}"', inhalt or "")


# ---------------------------------------------------------------------------
# Essay-Seite
# ---------------------------------------------------------------------------
def essay_seite(e, en=False):
    rel = "../../"
    v = e.get("en") if en else e
    if en and not v:
        return None
    titel = v.get("titel") or e.get("titel", "")
    beschreibung = kuerzen(v.get("leitthese") or v.get("untertitel") or "", 220)
    kanonisch = f"{SITE_URL}/{pfad_en(e) if en else pfad_de(e)}"
    alternate = {"de": f"{SITE_URL}/{pfad_de(e)}"}
    if e.get("en"):
        alternate["en"] = f"{SITE_URL}/{pfad_en(e)}"
    bild = (e.get("bild") or {}).get("url")

    teile = [kopf(f"{titel} – Der Korrespondent", beschreibung, rel, kanonisch, bild, "article",
                  "en" if en else "de", alternate), leiste(rel, en)]
    teile.append('<main class="page"><article>')
    teile.append(f'<div class="kicker">{esc(v.get("rubrik") or e.get("rubrik", ""))} · {esc(e.get("lesezeit", "").replace("Min. Lesezeit", "min read") if en else e.get("lesezeit", ""))}</div>')
    teile.append(f'<h1 class="headline">{esc(titel)}</h1>')
    if v.get("untertitel"):
        teile.append(f'<p class="subhead">{esc(v["untertitel"])}</p>')
    fc = e.get("faktencheck") or {}
    fc_text = ""
    if fc.get("geprueft"):
        n = len(fc.get("korrekturen", []))
        fc_text = (f" · Fact-checked against {fc.get('quellen', '')} sources" if en
                   else f" · Faktengeprüft gegen {fc.get('quellen', '')} Quellen, {n} Korrektur{'en' if n != 1 else ''}")
    other = (f'<a href="../../{pfad_de(e)}">Deutsche Fassung</a>' if en
             else (f'<a href="../../{pfad_en(e)}">English version</a>' if e.get("en") else ""))
    ki = "AI-generated" if en else "KI-erstellt"
    teile.append(f'<div class="meta-line"><strong>{ki}</strong> · {"Edition of" if en else "Ausgabe vom"} {esc(datum_lang(e["_datum"], en))}{fc_text}{" · " + other if other else ""}</div>')
    if bild:
        b = e["bild"]
        lizenz = esc(b.get("lizenz") or "Wikimedia Commons")
        if b.get("quelle"):
            lizenz = f'<a href="{esc(b["quelle"])}" target="_blank" rel="noopener noreferrer" style="color:inherit;">{lizenz}</a>'
        teile.append(f'<figure class="hero"><img onerror="this.parentNode.remove()" src="{esc(bild)}" alt="{esc(b.get("beschreibung", ""))}" loading="lazy">'
                     f'<figcaption>{lizenz}</figcaption></figure>')
    if v.get("kurzfassung"):
        teile.append(f'<div class="kurzfassung"><strong>{"In brief" if en else "In Kürze"}</strong><ul>'
                     + "".join(f"<li>{esc(k)}</li>" for k in v["kurzfassung"]) + "</ul></div>")
    teile.append(f'<div class="essay-body">{links_umschreiben(v.get("inhalt_html", ""), rel)}</div>')

    anker = v.get("historische_anker") or {}
    if anker:
        teile.append(f'<section class="box"><h2>{"Historical context" if en else "Historische Resonanz"}</h2>'
                     + "".join(f'<h3>{esc(a.get("titel", ""))}</h3><p>{esc(a.get("text", ""))}</p>' for a in anker.values() if isinstance(a, dict))
                     + "</section>")

    ws_de = e.get("weltspiegel") or []
    ws_txt = (v.get("weltspiegel") or []) if en else ws_de
    if ws_de:
        teile.append(f'<section class="box"><h2>{"World press review" if en else "Der Weltspiegel"}</h2>')
        for i, w in enumerate(ws_de):
            t = ws_txt[i] if i < len(ws_txt) else w
            teile.append(f'<div class="press-item"><div class="press-meta">{esc(w.get("medium"))} · {esc(t.get("tenor", w.get("tenor")))}</div>'
                         f'<p>{esc(t.get("zusammenfassung", w.get("zusammenfassung")))}</p>'
                         f'<a href="{esc(w.get("url"))}" target="_blank" rel="noopener noreferrer">{"Original article" if en else "Zum Originalbeitrag"} →</a></div>')
        teile.append("</section>")

    if e.get("quellen"):
        teile.append(f'<section class="box"><h2>{"Sources" if en else "Quellenbasis"}</h2><ul>'
                     + "".join(f'<li>{esc(q["medium"])} ({esc(q["land"])}): <a href="{esc(q["url"])}" target="_blank" rel="noopener noreferrer">{esc(q["titel"])}</a></li>'
                               for q in e["quellen"]) + "</ul></section>")
    if fc.get("korrekturen"):
        teile.append(f'<details class="box"><summary>{"Fact-check log" if en else "Prüfprotokoll des Faktenchecks"} ({len(fc["korrekturen"])})</summary><ul>'
                     + "".join(f'<li><em>„{esc(k.get("stelle"))}“</em> – {esc(k.get("problem"))} <strong>→</strong> {esc(k.get("korrektur"))}</li>'
                               for k in fc["korrekturen"]) + "</ul></details>")

    if e.get("schlagworte"):
        teile.append('<div class="tag-cloud">' + "".join(
            f'<a class="tag" href="{rel}themen/{slugify(s)}.html">{esc(s)}</a>' for s in e["schlagworte"]) + "</div>")
    app_link = f'{rel}index.html#/{e["_datum"]}/{e["_slug"]}' + ("?lang=en" if en else "")
    teile.append(f'<a class="cta" href="{app_link}">{"Read the full edition →" if en else "Zur ganzen Ausgabe →"}</a>')
    teile.append("</article></main>")
    teile.append(f"<script>window.ANKER = {json.dumps(anker, ensure_ascii=False)};</script>")
    teile.append(fuss(rel, en))
    return "".join(teile)


# ---------------------------------------------------------------------------
# Archiv & Dossiers
# ---------------------------------------------------------------------------
def teaser(e, rel):
    these = kuerzen(e.get("leitthese", ""), 180)
    suchtext = " ".join([e.get("titel", ""), e.get("untertitel", ""), e.get("leitthese", ""), e.get("rubrik", ""),
                         " ".join(e.get("schlagworte", []))]).lower()
    return (f'<a class="teaser" href="{rel}{pfad_de(e)}" data-suche="{esc(suchtext)}">'
            f'<span class="teaser-rubrik">{esc(e.get("rubrik", ""))}</span>'
            f'<span class="teaser-title">{esc(e.get("titel", ""))}</span>'
            f'<span class="teaser-these">{esc(these)}</span></a>')


SUCH_SCRIPT = """<script>
var feld = document.getElementById('suche');
feld.addEventListener('input', function () {
  var q = feld.value.trim().toLowerCase().split(/\\s+/).filter(Boolean);
  document.querySelectorAll('.teaser').forEach(function (t) {
    var s = t.getAttribute('data-suche');
    t.style.display = q.every(function (w) { return s.indexOf(w) !== -1; }) ? '' : 'none';
  });
  document.querySelectorAll('.edition, .month').forEach(function (b) {
    b.style.display = b.querySelector('.teaser:not([style*="none"])') ? '' : 'none';
  });
});
</script>"""


def archiv_seite(essays):
    rel = ""
    teile = [kopf("Archiv – Der Korrespondent", "Alle Ausgaben und Essays des Korrespondenten.", rel, f"{SITE_URL}/archiv.html"),
             leiste(rel), '<main class="page wide">', '<div class="kicker">Archiv</div>',
             '<h1 class="headline">Alle Ausgaben</h1>',
             f'<input id="suche" class="search" type="search" placeholder="Archiv durchsuchen – Titel, Thesen, Schlagworte …" aria-label="Archiv durchsuchen">']
    monat_alt = datum_alt = None
    for e in essays:
        monat = e["_datum"][:7]
        if monat != monat_alt:
            if monat_alt:
                teile.append("</div></section>")
            j, m = monat.split("-")
            teile.append(f'<section class="month"><h2>{MONATE[int(m) - 1]} {j}</h2><div>')
            monat_alt, datum_alt = monat, None
        if e["_datum"] != datum_alt:
            if datum_alt:
                teile.append("</div>")
            teile.append(f'<div class="edition"><h3>{esc(e["_ausgabe"])} · Nr. {esc(e["_nr"])}</h3>')
            datum_alt = e["_datum"]
        teile.append(teaser(e, rel))
    if monat_alt:
        teile.append("</div></div></section>")
    teile.append("</main>" + SUCH_SCRIPT + fuss(rel))
    return "".join(teile)


def dossiers(essays):
    nach_thema = {}
    for e in essays:
        for s in e.get("schlagworte", []) or []:
            key = slugify(s)
            nach_thema.setdefault(key, {"name": s, "essays": []})["essays"].append(e)
    return nach_thema


def dossier_index(themen):
    rel = "../"
    sortiert = sorted(themen.items(), key=lambda kv: (-len(kv[1]["essays"]), kv[1]["name"].lower()))
    teile = [kopf("Dossiers – Der Korrespondent", "Alle Essays nach Themen geordnet.", rel, f"{SITE_URL}/themen/index.html"),
             leiste(rel), '<main class="page wide"><div class="kicker">Dossiers</div><h1 class="headline">Themen</h1>',
             '<p class="subhead">Jedes Thema, das der Korrespondent begleitet – mit allen Essays in zeitlicher Folge.</p>',
             '<div class="tag-cloud" style="margin-top:2rem">']
    for key, t in sortiert:
        teile.append(f'<a class="tag" href="{key}.html">{esc(t["name"])} <small>{len(t["essays"])}</small></a>')
    teile.append("</div></main>" + fuss(rel))
    return "".join(teile)


def dossier_seite(key, t):
    rel = "../"
    name = t["name"]
    n = len(t["essays"])
    teile = [kopf(f"Dossier: {name} – Der Korrespondent", f"{n} Essay{'s' if n != 1 else ''} zum Thema {name}.", rel,
                  f"{SITE_URL}/themen/{key}.html"),
             leiste(rel), f'<main class="page"><div class="kicker">Dossier · {n} Essay{"s" if n != 1 else ""}</div>',
             f'<h1 class="headline">{esc(name)}</h1><div style="margin-top:2rem">']
    for e in t["essays"]:
        teile.append(f'<div class="edition"><h3>{esc(datum_lang(e["_datum"]))}</h3>{teaser(e, rel)}</div>')
    teile.append('</div><a class="cta" href="index.html">Alle Dossiers →</a></main>' + fuss(rel))
    return "".join(teile)


# ---------------------------------------------------------------------------
# Feed & Sitemap
# ---------------------------------------------------------------------------
def rss(essays):
    items = []
    for e in essays[:40]:
        d = datetime.strptime(e["_datum"], "%Y-%m-%d").replace(hour=6, tzinfo=TZ)
        link = f"{SITE_URL}/{pfad_de(e)}"
        beschreibung = esc(e.get("leitthese") or e.get("untertitel") or "")
        bild = (e.get("bild") or {}).get("url")
        enclosure = f'\n      <enclosure url="{esc(bild)}" type="image/jpeg" length="0"/>' if bild else ""
        items.append(f"""    <item>
      <title>{esc(e.get('titel', ''))}</title>
      <link>{link}</link>
      <guid isPermaLink="true">{link}</guid>
      <pubDate>{format_datetime(d)}</pubDate>
      <category>{esc(e.get('rubrik', ''))}</category>
      <description>{beschreibung}</description>{enclosure}
    </item>""")
    jetzt = format_datetime(datetime.now(TZ))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Der Korrespondent</title>
    <link>{SITE_URL}/</link>
    <atom:link href="{SITE_URL}/feed.xml" rel="self" type="application/rss+xml"/>
    <description>KI-erstellte, automatisch faktengeprüfte Essays zur Lage der Gegenwart – historisch geerdet, europäisch gedacht.</description>
    <language>de-de</language>
    <lastBuildDate>{jetzt}</lastBuildDate>
{chr(10).join(items)}
  </channel>
</rss>
"""


def sitemap(urls):
    eintraege = "\n".join(f"  <url><loc>{esc(u)}</loc>{f'<lastmod>{d}</lastmod>' if d else ''}</url>" for u, d in urls)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{eintraege}
</urlset>
"""


# ---------------------------------------------------------------------------
def schreibe(pfad, inhalt):
    os.makedirs(os.path.dirname(pfad) or ".", exist_ok=True)
    with open(pfad, "w", encoding="utf-8") as f:
        f.write(inhalt)


def main():
    essays = lade_alle_essays()
    if not essays:
        sys.exit("Archiv leer – nichts zu bauen.")
    for ordner in ("artikel", "en", "themen"):
        shutil.rmtree(ordner, ignore_errors=True)

    urls = [(f"{SITE_URL}/", essays[0]["_datum"]), (f"{SITE_URL}/archiv.html", essays[0]["_datum"]),
            (f"{SITE_URL}/themen/index.html", essays[0]["_datum"])]
    n_en = 0
    for e in essays:
        schreibe(pfad_de(e), essay_seite(e))
        urls.append((f"{SITE_URL}/{pfad_de(e)}", e["_datum"]))
        seite_en = essay_seite(e, en=True)
        if seite_en:
            schreibe(pfad_en(e), seite_en)
            urls.append((f"{SITE_URL}/{pfad_en(e)}", e["_datum"]))
            n_en += 1

    schreibe("archiv.html", archiv_seite(essays))
    themen = dossiers(essays)
    schreibe("themen/index.html", dossier_index(themen))
    for key, t in themen.items():
        schreibe(f"themen/{key}.html", dossier_seite(key, t))
        urls.append((f"{SITE_URL}/themen/{key}.html", t["essays"][0]["_datum"]))

    schreibe("feed.xml", rss(essays))
    schreibe("sitemap.xml", sitemap(urls))
    schreibe("robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n")
    print(f"Seiten gebaut: {len(essays)} Essays (+{n_en} englisch), {len(themen)} Dossiers, Archiv, Feed, Sitemap.")


if __name__ == "__main__":
    main()
