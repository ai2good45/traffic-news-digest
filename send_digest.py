import smtplib
import feedparser
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone
import os
from bs4 import BeautifulSoup

# --- הגדרות ---
TO_EMAIL = "hofit2good@gmail.com , amir.cohen@nokia.com , amir2good@gmail.com"
FROM_EMAIL = os.environ["GMAIL_USER"]
GMAIL_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]

CUTOFF_HOURS = 24
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ================================================================
# פונקציות עזר
# ================================================================

def is_recent(published_parsed):
    if not published_parsed:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CUTOFF_HOURS)
    pub_dt = datetime(*published_parsed[:6], tzinfo=timezone.utc)
    return pub_dt >= cutoff

def fmt_date(published_parsed):
    if not published_parsed:
        return ""
    return datetime(*published_parsed[:6]).strftime("%d/%m %H:%M")

# ================================================================
# 1. חדשות תעבורה כלליות — Google News RSS
# ================================================================

FEEDS = [
    "https://news.google.com/rss/search?q=תעבורה+ישראל&hl=he&gl=IL&ceid=IL:he",
    "https://news.google.com/rss/search?q=תחבורה+ציבורית+ישראל&hl=he&gl=IL&ceid=IL:he",
    "https://news.google.com/rss/search?q=כבישים+תאונות+ישראל&hl=he&gl=IL&ceid=IL:he",
]

def fetch_news_articles():
    articles = []
    seen_titles = set()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CUTOFF_HOURS)

    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                title = entry.get("title", "").strip()
                if not title or title in seen_titles:
                    continue
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                if not published:
                    continue
                pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                if pub_dt < cutoff:
                    continue
                seen_titles.add(title)
                articles.append({
                    "title": title,
                    "summary": entry.get("summary", "")[:200],
                    "link": entry.get("link", ""),
                    "source": feed.feed.get("title", "Google News"),
                    "published": fmt_date(published)
                })
        except Exception as e:
            print(f"שגיאה ב-RSS {url}: {e}")

    articles.sort(key=lambda a: a.get("published", ""), reverse=True)
    return articles

# ================================================================
# 2. הודעות משרד התחבורה — gov.il API
# ================================================================

def fetch_mot_announcements():
    articles = []
    yesterday = datetime.now() - timedelta(days=1)
    date_str = yesterday.strftime("%Y-%m-%d")
    url = "https://www.gov.il/he/api/CoveoSearch"
    payload = {
        "q": "",
        "numberOfResults": 20,
        "sortCriteria": "@date descending",
        "fieldsToInclude": ["title", "date", "excerpt", "clickUri"],
        "aq": f'@source=="משרד התחבורה" AND @date>="{date_str}"',
        "locale": "he"
    }
    try:
        r = requests.post(url, json=payload, headers={**HEADERS, "Content-Type": "application/json"}, timeout=15)
        if r.status_code == 200:
            for item in r.json().get("results", []):
                articles.append({
                    "title": item.get("title", "ללא כותרת"),
                    "summary": item.get("excerpt", "")[:250],
                    "link": item.get("clickUri", "https://www.gov.il/he/departments/ministry_of_transport_and_road_safety"),
                    "source": "משרד התחבורה",
                    "published": ""
                })
    except Exception as e:
        print(f"שגיאה בשליפת gov.il: {e}")
    return articles

# ================================================================
# 3. מכרזים ופטורים — חשב הכללי
# ================================================================

def fetch_tenders():
    results = []
    sources = [
        ("https://mr.gov.il/ilgstorefront/he/search/?q=%3AupdateDate%3Aarchive%3Afalse&text=&s=TENDER#", "מכרז — חשב הכללי"),
        ("https://mr.gov.il/ilgstorefront/he/search/?q=%3AupdateDate%3Aarchive%3Afalse&text=&s=EXEMPTION#", "פטור ממכרז — חשב הכללי"),
    ]
    for url, source_name in sources:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            seen = set()
            for item in soup.select("li.product__item, div.product__item, div[class*='result'], li[class*='result']")[:15]:
                a = item.find("a")
                title_el = item.find(["h2", "h3", "h4", "span"], class_=lambda c: c and "name" in str(c).lower())
                title = (title_el or a).get_text(strip=True)[:150] if (title_el or a) else ""
                if not title or title in seen or len(title) < 5:
                    continue
                seen.add(title)
                link = a.get("href", url) if a else url
                if not link.startswith("http"):
                    link = "https://mr.gov.il" + link
                summary_el = item.find(["p", "span"], class_=lambda c: c and "desc" in str(c).lower())
                results.append({
                    "title": title,
                    "summary": summary_el.get_text(strip=True)[:200] if summary_el else "",
                    "link": link,
                    "source": source_name,
                    "published": ""
                })
        except Exception as e:
            print(f"שגיאה בשליפת {source_name}: {e}")
    return results

# ================================================================
# 4. מכרזי רכבת ישראל
# ================================================================

def fetch_rail_tenders():
    results = []
    url = "https://rail.co.il/?page=GeneralAuctions&lan=he"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            seen = set()
            rows = soup.select("table tr")[1:16]
            for row in rows:
                cols = row.find_all("td")
                if not cols:
                    continue
                title = cols[0].get_text(strip=True)
                if not title or title in seen or len(title) < 5:
                    continue
                seen.add(title)
                a = row.find("a")
                link = a.get("href", url) if a else url
                if not link.startswith("http"):
                    link = "https://rail.co.il/" + link.lstrip("/")
                results.append({
                    "title": title,
                    "summary": cols[1].get_text(strip=True)[:200] if len(cols) > 1 else "",
                    "link": link,
                    "source": "מכרזי רכבת ישראל",
                    "published": cols[-1].get_text(strip=True) if len(cols) > 2 else ""
                })
    except Exception as e:
        print(f"שגיאה במכרזי רכבת: {e}")
    return results

# ================================================================
# 5. אזהרות מסע — מלל
# ================================================================

def fetch_travel_warnings():
    results = []
    try:
        url = "https://www.gov.il/he/Departments/DynamicCollectors/travel-warnings-nsc?skip=0"
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            ct = r.headers.get("Content-Type", "")
            if "json" in ct:
                data = r.json()
                for item in data.get("items", data.get("results", []))[:10]:
                    title = item.get("title", item.get("Title", ""))[:150]
                    if not title:
                        continue
                    results.append({
                        "title": title,
                        "summary": item.get("description", item.get("Description", ""))[:200],
                        "link": item.get("url", item.get("Url", url)),
                        "source": "אזהרות מסע — מלל",
                        "published": ""
                    })
            else:
                soup = BeautifulSoup(r.text, "html.parser")
                seen = set()
                for card in soup.select("div[class*='card'], div[class*='item'], li[class*='item']")[:10]:
                    a = card.find("a")
                    title = a.get_text(strip=True) if a else card.get_text(strip=True)[:100]
                    if not title or title in seen or len(title) < 5:
                        continue
                    seen.add(title)
                    link = a.get("href", url) if a else url
                    results.append({
                        "title": title, "summary": "", "link": link,
                        "source": "אזהרות מסע — מלל", "published": ""
                    })
    except Exception as e:
        print(f"שגיאה באזהרות מסע: {e}")
    return results

# ================================================================
# 6. ועדות כנסת
# ================================================================

def fetch_knesset_committee(committee_id, name):
    results = []
    url = f"https://main.knesset.gov.il/APPS/committees/{committee_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            seen = set()
            for a in soup.select("a[href*='meeting'], a[href*='Meeting'], div[class*='row'] a, li a")[:15]:
                title = a.get_text(strip=True)
                if not title or title in seen or len(title) < 8:
                    continue
                seen.add(title)
                link = a.get("href", url)
                if not link.startswith("http"):
                    link = "https://main.knesset.gov.il" + link
                results.append({
                    "title": title, "summary": "", "link": link,
                    "source": name, "published": ""
                })
    except Exception as e:
        print(f"שגיאה ב{name}: {e}")
    return results[:6]

# ================================================================
# 7. רשויות ממשלתיות — ספנות, רלב"ד, שדות תעופה
# ================================================================

GOV_AGENCIES = [
    ("https://www.gov.il/he/departments/authority_of_shipping_and_ports/govil-landing-page", "רשות הספנות והנמלים"),
    ("https://www.gov.il/he/departments/israel_national_road_safety_authority/govil-landing-page", 'הרלב"ד'),
    ("https://www.gov.il/he/departments/civil_aviation_authority_of_israel/govil-landing-page", "רשות התעופה האזרחית"),
]

def fetch_gov_agency(url, name):
    results = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            seen = set()
            for card in soup.select("div[class*='card'], div[class*='news'], div[class*='update'], article")[:10]:
                a = card.find("a")
                title_el = card.find(["h2", "h3", "h4", "span"])
                title = title_el.get_text(strip=True) if title_el else (a.get_text(strip=True) if a else "")
                if not title or title in seen or len(title) < 5:
                    continue
                seen.add(title)
                link = a.get("href", url) if a else url
                if not link.startswith("http"):
                    link = "https://www.gov.il" + link
                desc_el = card.find("p")
                results.append({
                    "title": title,
                    "summary": desc_el.get_text(strip=True)[:200] if desc_el else "",
                    "link": link,
                    "source": name,
                    "published": ""
                })
    except Exception as e:
        print(f"שגיאה ב{name}: {e}")
    return results[:5]

# ================================================================
# 8. מקורות בינלאומיים — Reuters, EASA, IATA, OECD, Maersk
#    סינון: חייב להכיל ישראל + תחבורה/תעופה/ספנות
# ================================================================

ISRAEL_KW  = ["israel", "israeli", "tel aviv", "haifa", "ashdod", "eilat", "ben gurion"]
TRANSPORT_KW = ["transport", "aviation", "airport", "airline", "flight", "port", "shipping",
                "maritime", "vessel", "rail", "road", "traffic", "freight", "cargo",
                "logistics", "infrastructure", "highway", "tunnel", "bridge"]

INTL_FEEDS = [
    ("https://news.google.com/rss/search?q=Israel+transport+OR+aviation+OR+shipping+OR+port+OR+airport+source:reuters.com&hl=en&gl=IL&ceid=IL:en", "Reuters"),
    ("https://www.easa.europa.eu/en/rss.xml", "EASA"),
    ("https://www.iata.org/en/pressroom/rss/", "IATA"),
    ("https://news.google.com/rss/search?q=OECD+Israel+transport+OR+infrastructure+OR+aviation&hl=en&gl=IL&ceid=IL:en", "OECD"),
    ("https://news.google.com/rss/search?q=Maersk+Israel&hl=en&gl=IL&ceid=IL:en", "Maersk"),
]

def fetch_international():
    results = []
    seen_titles = set()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CUTOFF_HOURS)

    for feed_url, source_name in INTL_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                title = entry.get("title", "").strip()
                summary = entry.get("summary", "")
                if not title or title in seen_titles:
                    continue

                published = entry.get("published_parsed") or entry.get("updated_parsed")
                if published:
                    pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue

                text = (title + " " + summary).lower()

                # EASA ו-IATA: חייב להזכיר ישראל
                if source_name in ["EASA", "IATA"]:
                    if not any(kw in text for kw in ISRAEL_KW):
                        continue
                else:
                    # Reuters, OECD, Maersk: ישראל + תחבורה
                    if not any(kw in text for kw in ISRAEL_KW):
                        continue
                    if not any(kw in text for kw in TRANSPORT_KW):
                        continue

                seen_titles.add(title)
                results.append({
                    "title": title,
                    "summary": summary[:200],
                    "link": entry.get("link", ""),
                    "source": source_name,
                    "published": fmt_date(published) if published else ""
                })
        except Exception as e:
            print(f"שגיאה ב-{source_name}: {e}")

    return results

# ================================================================
# בניית המייל
# ================================================================

def section_html(title, color_bg, color_border, color_title, items, empty_msg):
    count = len(items)
    html = f"""
    <div style="background:{color_bg}; border-radius:8px; padding:16px; margin-bottom:24px;">
      <h3 style="color:{color_title}; margin-top:0;">{title} ({count})</h3>
    """
    if items:
        for i, a in enumerate(items, 1):
            pub = f"&nbsp;|&nbsp;<small style='color:#999;'>{a['published']}</small>" if a.get("published") else ""
            summary_block = f"<span style='color:#555; font-size:0.9em;'>{a['summary']}</span><br>" if a.get("summary") else ""
            html += f"""
            <div style="background:white; border-radius:6px; padding:12px; margin-bottom:10px; border-right:4px solid {color_border};">
              <strong>{i}. {a['title']}</strong><br>
              {summary_block}
              <a href="{a['link']}" style="color:{color_border}; font-size:0.85em;">קרא עוד ←</a>
              <small style="color:#999;"> — {a['source']}</small>{pub}
            </div>"""
    else:
        html += f'<p style="color:#888;">{empty_msg}</p>'
    html += "</div>"
    return html

def build_email(data):
    date_str = datetime.now().strftime("%d/%m/%Y")
    total = sum(len(v) for v in data.values())

    html = f"""
    <html><body dir="rtl" style="font-family: Arial; max-width: 750px; margin: auto; direction: rtl;">
    <h2 style="color:#1a365d; border-bottom:3px solid #2b6cb0; padding-bottom:10px;">
      📰 סיכום תחבורה יומי — {date_str}
      <small style="font-size:0.65em; color:#555;"> ({total} פריטים)</small>
    </h2>
    """

    html += section_html("🏛️ הודעות משרד התחבורה",
                         "#ebf8ff", "#2b6cb0", "#2b6cb0", data["mot"],
                         "לא נמצאו הודעות חדשות מהמשרד היום.")

    html += section_html("📄 מכרזים ופטורים — חשב הכללי",
                         "#fffbeb", "#d97706", "#92400e", data["tenders"],
                         "לא נמצאו מכרזים חדשים.")

    html += section_html("🚂 מכרזי רכבת ישראל",
                         "#fef3c7", "#b45309", "#92400e", data["rail_tenders"],
                         "לא נמצאו מכרזים חדשים ברכבת.")

    html += section_html("⚠️ אזהרות מסע — מלל",
                         "#fff5f5", "#e53e3e", "#c53030", data["travel_warnings"],
                         "אין אזהרות מסע חדשות.")

    html += section_html("🏛️ ועדת הכלכלה של הכנסת",
                         "#f0fff4", "#38a169", "#276749", data["knesset_economy"],
                         "אין פריטים חדשים.")

    html += section_html("💰 ועדת הכספים של הכנסת",
                         "#f7fff0", "#2f855a", "#276749", data["knesset_finance"],
                         "אין פריטים חדשים.")

    html += section_html("⚓ רשות הספנות והנמלים",
                         "#e6fffa", "#319795", "#234e52", data["shipping"],
                         "אין עדכונים.")

    html += section_html('🛣️ הרלב"ד',
                         "#ebf8ff", "#3182ce", "#2c5282", data["ralbad"],
                         "אין עדכונים.")

    html += section_html("✈️ רשות התעופה האזרחית",
                         "#f0f4ff", "#5a67d8", "#3c366b", data["aviation"],
                         "אין עדכונים.")

    html += section_html("🌍 מקורות בינלאומיים — Reuters / EASA / IATA / OECD / Maersk",
                         "#faf5ff", "#805ad5", "#553c9a", data["international"],
                         "לא נמצאו פרסומים חדשים הקשורים לישראל.")

    html += section_html("📡 חדשות תעבורה מהתקשורת",
                         "#f0fff4", "#48bb78", "#276749", data["news"],
                         "לא נמצאו כתבות היום.")

    html += "</body></html>"
    return html

# ================================================================
# שליחת מייל
# ================================================================

def send_email(html_content):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🚗 חדשות תעבורה מהאח הכי הכי ❤️ — {datetime.now().strftime('%d/%m/%Y')}"
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL
    msg.attach(MIMEText(html_content, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(FROM_EMAIL, GMAIL_PASSWORD)
        server.send_message(msg)
    print("✅ מייל נשלח בהצלחה!")

# ================================================================
# MAIN
# ================================================================

if __name__ == "__main__":
    print("📥 שולף חדשות תעבורה (Google News)...")
    news = fetch_news_articles()

    print("🏛️ שולף הודעות משרד התחבורה...")
    mot = fetch_mot_announcements()

    print("📄 שולף מכרזים — חשב הכללי...")
    tenders = fetch_tenders()

    print("🚂 שולף מכרזי רכבת...")
    rail_tenders = fetch_rail_tenders()

    print("⚠️ שולף אזהרות מסע...")
    travel_warnings = fetch_travel_warnings()

    print("🏛️ שולף ועדת הכלכלה...")
    knesset_economy = fetch_knesset_committee(2214, "ועדת הכלכלה")

    print("💰 שולף ועדת כספים...")
    knesset_finance = fetch_knesset_committee(2213, "ועדת הכספים")

    print("⚓ שולף רשויות ממשלתיות...")
    shipping = fetch_gov_agency(GOV_AGENCIES[0][0], GOV_AGENCIES[0][1])
    ralbad   = fetch_gov_agency(GOV_AGENCIES[1][0], GOV_AGENCIES[1][1])
    aviation = fetch_gov_agency(GOV_AGENCIES[2][0], GOV_AGENCIES[2][1])

    print("🌍 שולף מקורות בינלאומיים...")
    international = fetch_international()

    data = {
        "mot": mot,
        "tenders": tenders,
        "rail_tenders": rail_tenders,
        "travel_warnings": travel_warnings,
        "knesset_economy": knesset_economy,
        "knesset_finance": knesset_finance,
        "shipping": shipping,
        "ralbad": ralbad,
        "aviation": aviation,
        "international": international,
        "news": news,
    }

    total = sum(len(v) for v in data.values())
    print(f'✅ סה"כ {total} פריטים נמצאו')

    html = build_email(data)
    send_email(html)
