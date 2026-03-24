import smtplib
import feedparser
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone
import os
import urllib.parse
from bs4 import BeautifulSoup

# --- הגדרות ---
TO_EMAIL = "hofit2good@gmail.com , amir.cohen@nokia.com , amir2good@gmail.com"
FROM_EMAIL = os.environ["GMAIL_USER"]
GMAIL_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]

CUTOFF_HOURS = 24
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
}

# ================================================================
# מילות מפתח לסינון תוכן — תחבורה (מורחב)
# ================================================================

HE_KEYWORDS = [
    # משרדים ורשויות
    "משרד התחבורה", "משרד האוצר", "רשות התחבורה",
    # כבישים ותנועה
    "כבישים", "כביש", "מחלף", "מחלף", "פקק", "עומס תנועה",
    "נתיבי איילון", "נתיבי ישראל", "כביש 6", "כביש חוצה ישראל",
    "נתיב מהיר", "נתיב", "צומת", "גשר", "מנהרה",
    "עבודות כביש", "תמרורים", "מהירות", "מכמונת",
    "משטרת תנועה", "שוטר תנועה", "תנועה", "תעבורה",
    # תאונות ובטיחות
    "תאונה", "תאונות", "תאונת דרכים", "פגע וברח",
    "בטיחות בדרכים", "הרשות הלאומית לבטיחות בדרכים", 'רלב"ד',
    "קטלניות", "נהג", "אופנוע", "אופניים", "קורקינט",
    # תחבורה ציבורית
    "תחבורה ציבורית", "תחבורה", "אוטובוס", "אוטובוסים",
    "קו אוטובוס", "תחנת אוטובוס", "תחנה מרכזית",
    "אגד", "דן", "מטרופולין", "קווים", 'נת"ע',
    "רכבת", "רכבת ישראל", "תחנת רכבת", "רכבת קלה",
    "מטרו", "קו רכבת", "מסילה",
    "מונית", "מוניות", "שירות מוניות", "מוניות שיתופיות",
    # תעופה
    "תעופה", "נמל תעופה", "שדה תעופה", 'נתב"ג',
    "אלעל", "אל על", "ישראייר", "ארקיע", "אייר חיפה",
    "טיסה", "טיסות", "מטוס", "מטוסים", "נוסעים",
    "רשות שדות התעופה", "רשות התעופה האזרחית",
    "EASA", "IATA", "מסוף",
    # ימאות ונמלים
    "נמל", "נמלים", "נמל חיפה", "נמל אשדוד", "נמל אילת", "נמל הדרום",
    "ספנות", "ים", "כלי שיט", "אוניה", "מכולות", "מטען ים",
    "מספנות ישראל", "ממגורות חיפה", "דגון",
    # לוגיסטיקה ותשתיות
    "לוגיסטיקה", "שילוח", "מטען", "יבוא", "יצוא",
    "תשתיות תחבורה", "תשתיות", "הסעות",
    "נסיעה", "נסיעות", "נוסע",
    # מכרזים ורגולציה
    "מכרז", "פטור ממכרז", "הקצאה", "רישיון",
    # אנשים מרכזיים
    "מירי רגב", "משה בן זקן", "עידן מועלם",
]

def is_transport_related(title, summary=""):
    """בודק אם הפריט קשור לתחבורה לפי מילות המפתח"""
    text = title + " " + summary
    return any(kw in text for kw in HE_KEYWORDS)

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
# 1. חדשות תעבורה כלליות — Google News RSS (מורחב)
# ================================================================

FEEDS = [
    "https://news.google.com/rss/search?q=תעבורה+ישראל&hl=he&gl=IL&ceid=IL:he",
    "https://news.google.com/rss/search?q=תחבורה+ציבורית+ישראל&hl=he&gl=IL&ceid=IL:he",
    "https://news.google.com/rss/search?q=כבישים+תאונות+ישראל&hl=he&gl=IL&ceid=IL:he",
    "https://news.google.com/rss/search?q=רכבת+ישראל+חדשות&hl=he&gl=IL&ceid=IL:he",
    "https://news.google.com/rss/search?q=אל+על+ישראייר+ארקיע&hl=he&gl=IL&ceid=IL:he",
    "https://news.google.com/rss/search?q=נמל+חיפה+אשדוד+ספנות&hl=he&gl=IL&ceid=IL:he",
    "https://news.google.com/rss/search?q=משטרת+תנועה+תאונה+כביש&hl=he&gl=IL&ceid=IL:he",
    "https://news.google.com/rss/search?q=אוטובוס+מוניות+תחבורה+ציבורית&hl=he&gl=IL&ceid=IL:he",
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
                title   = item.get("title", "ללא כותרת")
                summary = item.get("excerpt", "")[:250]
                if not is_transport_related(title, summary):
                    continue
                articles.append({
                    "title": title,
                    "summary": summary,
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
    # מילות מפתח ספציפיות לתחבורה במכרזים
    tender_transport_kw = [
        "תחבורה", "כביש", "נסיעה", "אוטובוס", "רכבת", "תעופה", "נמל",
        "ספנות", "לוגיסטי", "הסעה", "שינוע", "רכב", "הולכי רגל",
        "מסילה", "מדרכה", "תמרור", "גשר", "מנהרה", "חניה",
        "מטוס", "שדה תעופה", "ים", "שילוח", "מטען"
    ]
    for url, source_name in sources:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            seen = set()
            # selectors מורחבים
            items = soup.select("li.product__item, div.product__item, div[class*='result'], li[class*='result'], article, div[class*='tender'], div[class*='item']")[:20]
            for item in items:
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
                summary = summary_el.get_text(strip=True)[:200] if summary_el else ""
                # סינון רלוונטיות — רחב יותר למכרזים
                text = title + " " + summary
                if not (is_transport_related(title, summary) or
                        any(kw in text for kw in tender_transport_kw)):
                    continue
                results.append({
                    "title": title,
                    "summary": summary,
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
                summary = cols[1].get_text(strip=True)[:200] if len(cols) > 1 else ""
                results.append({
                    "title": title,
                    "summary": summary,
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
                    title   = item.get("title", item.get("Title", ""))[:150]
                    summary = item.get("description", item.get("Description", ""))[:200]
                    if not title or not is_transport_related(title, summary):
                        continue
                    results.append({
                        "title": title,
                        "summary": summary,
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
                    if not is_transport_related(title):
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
                if not is_transport_related(title):
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
                desc_el = card.find("p")
                summary = desc_el.get_text(strip=True)[:200] if desc_el else ""
                if not is_transport_related(title, summary):
                    continue
                seen.add(title)
                link = a.get("href", url) if a else url
                if not link.startswith("http"):
                    link = "https://www.gov.il" + link
                results.append({
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "source": name,
                    "published": ""
                })
    except Exception as e:
        print(f"שגיאה ב{name}: {e}")
    return results[:5]

# ================================================================
# 8. בורסה לניירות ערך — MAYA דיווחים מיידיים
#    משתמש ב-API האמיתי של mayaapi.tase.co.il
# ================================================================

TASE_COMPANIES = [
    "אל על", "אלעל", "ELAL",
    "ישראייר", "ISRAIR",
    "ארקיע", "ARKIA",
    "אייר חיפה",
    "נמל אשדוד", "נמל חיפה", "נמל אילת", "נמל הדרום",
    "נתיבי איילון",
    "כביש חוצה ישראל", "כביש 6",
    "אגד", "דן",
    "מספנות ישראל",
    "ממגורות חיפה", "דגון",
    "רשות שדות התעופה",
]

TASE_KEYWORDS = TASE_COMPANIES + [
    "תחבורה", "תעבורה", "תעופה", "נמל", "ספנות",
    "אוטובוס", "רכבת", "כביש", "נוסעים", "טיסה",
    "מטען", "לוגיסטיקה", "שילוח", "מסילה",
]

MAYA_API_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "he-IL,he;q=0.9",
    "Origin": "https://maya.tase.co.il",
    "Referer": "https://maya.tase.co.il/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
}

def fetch_tase_reports():
    results = []
    seen_titles = set()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CUTOFF_HOURS)
    date_from = cutoff.strftime("%Y-%m-%d")
    date_to   = datetime.now().strftime("%Y-%m-%d")

    # ── שיטה 1: API ישיר של MAYA ──────────────────────────────────
    api_url = (
        f"https://mayaapi.tase.co.il/api/report/allreports"
        f"?categoryId=0&companyId=0&from={date_from}&to={date_to}&language=1"
    )
    try:
        r = requests.get(api_url, headers=MAYA_API_HEADERS, timeout=15)
        if r.status_code == 200:
            data = r.json()
            # ה-API מחזיר { Reports: [...] } או רשימה ישירה
            reports = data.get("Reports", data) if isinstance(data, dict) else data
            if isinstance(reports, list):
                for rep in reports:
                    title   = rep.get("Header", rep.get("Title", rep.get("ReportTitle", ""))).strip()
                    company = rep.get("CompanyName", rep.get("Company", ""))
                    report_id = rep.get("ReportId", rep.get("Id", ""))
                    if not title or title in seen_titles:
                        continue
                    text = title + " " + company
                    if not any(kw in text for kw in TASE_KEYWORDS):
                        continue
                    seen_titles.add(title)
                    link = f"https://maya.tase.co.il/he/reports/{report_id}" if report_id else "https://maya.tase.co.il"
                    pub_str = rep.get("PubDate", rep.get("Date", date_from))
                    if pub_str:
                        pub_str = pub_str[:10]
                    results.append({
                        "title": f"{company} — {title}" if company else title,
                        "summary": "",
                        "link": link,
                        "source": 'MAYA — בורסה לני"ע',
                        "published": pub_str or date_from,
                    })
    except Exception as e:
        print(f"שגיאה ב-MAYA API: {e}")

    # ── שיטה 2: גיבוי — Google News לחיפוש MAYA ──────────────────
    if len(results) < 3:
        print("MAYA API לא החזיר תוצאות, מנסה Google News כגיבוי...")
        maya_backup_feeds = [
            f"https://news.google.com/rss/search?q=site:maya.tase.co.il+תחבורה+OR+תעופה+OR+נמל&hl=he&gl=IL&ceid=IL:he",
            f"https://news.google.com/rss/search?q=אל+על+ישראייר+בורסה+דיווח&hl=he&gl=IL&ceid=IL:he",
            f"https://news.google.com/rss/search?q=ישראייר+נמל+תחבורה+בורסה&hl=he&gl=IL&ceid=IL:he",
        ]
        for feed_url in maya_backup_feeds:
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
                    if not any(kw in (title + " " + summary) for kw in TASE_KEYWORDS):
                        continue
                    seen_titles.add(title)
                    results.append({
                        "title": title,
                        "summary": summary[:200],
                        "link": entry.get("link", ""),
                        "source": 'MAYA / חדשות בורסה',
                        "published": fmt_date(published) if published else date_from,
                    })
            except Exception as e:
                print(f"שגיאה ב-MAYA גיבוי: {e}")

    results.sort(key=lambda a: a.get("published", ""), reverse=True)
    return results

# ================================================================
# 9. מקורות בינלאומיים — Reuters, EASA, IATA, OECD, Maersk
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

                if source_name in ["EASA", "IATA"]:
                    if not any(kw in text for kw in ISRAEL_KW):
                        continue
                else:
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
            pub = a.get("published", "")
            date_badge = (
                f"<span style='background:#f0f0f0; color:#555; font-size:0.78em; "
                f"padding:2px 6px; border-radius:4px; margin-right:6px;'>📅 {pub}</span>"
                if pub else
                "<span style='background:#f0f0f0; color:#aaa; font-size:0.78em; "
                "padding:2px 6px; border-radius:4px; margin-right:6px;'>📅 לא ידוע</span>"
            )
            summary_block = f"<span style='color:#555; font-size:0.9em;'>{a['summary']}</span><br>" if a.get("summary") else ""
            html += f"""
            <div style="background:white; border-radius:6px; padding:12px; margin-bottom:10px; border-right:4px solid {color_border};">
              <strong>{i}. {a['title']}</strong><br>
              {summary_block}
              {date_badge}
              <a href="{a['link']}" style="color:{color_border}; font-size:0.85em;">קרא עוד ←</a>
              <small style="color:#999;"> — {a['source']}</small>
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

    html += section_html("📈 בורסה לניירות ערך — דיווחים מיידיים (MAYA)",
                         "#fff8f0", "#ed8936", "#c05621", data["tase"],
                         "לא נמצאו דיווחים חדשים של חברות תחבורה.")

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
    msg["Subject"] = f"V4🚗 חדשות תעבורה מהאח הכי הכי ❤️ — {datetime.now().strftime('%d/%m/%Y')}"
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

    print("📈 שולף דיווחי בורסה (MAYA API)...")
    tase = fetch_tase_reports()

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
        "tase": tase,
        "international": international,
        "news": news,
    }

    total = sum(len(v) for v in data.values())
    print(f'✅ סה"כ {total} פריטים נמצאו')

    html = build_email(data)
    send_email(html)
