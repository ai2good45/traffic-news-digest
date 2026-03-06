import smtplib
import feedparser
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import os

# --- הגדרות ---
TO_EMAIL = "hofit2good@gmail.com , amir.cohen@nokia.com"  # ← שנה לכתובת היעד
FROM_EMAIL = os.environ["GMAIL_USER"]              # ← לא לשנות!
GMAIL_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]  # ← לא לשנות!

# RSS feeds חדשות תעבורה
FEEDS = [
    "https://www.ynet.co.il/Integration/StoryRss2.xml",
    "https://www.mako.co.il/rss/31",
    "https://www.walla.co.il/rss/1264",
]

KEYWORDS = [
    "תעבורה", "כביש", "נסיעה", "תאונה", "פקק", "רכבת",
    "אוטובוס", "מחלף", "עומס", "תחבורה ציבורית", "נתיב מהיר"
]

def fetch_news_articles():
    articles = []
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                title = entry.get("title", "")
                summary = entry.get("summary", "")
                if any(kw in title or kw in summary for kw in KEYWORDS):
                    articles.append({
                        "title": title,
                        "summary": summary[:200],
                        "link": entry.get("link", ""),
                        "source": feed.feed.get("title", url)
                    })
        except Exception as e:
            print(f"שגיאה ב-feed {url}: {e}")
    return articles

def fetch_mot_announcements():
    articles = []
    yesterday = datetime.now() - timedelta(days=1)
    date_str = yesterday.strftime("%Y-%m-%d")

    url = "https://www.gov.il/he/api/CoveoSearch"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.gov.il/he/departments/ministry_of_transport_and_road_safety"
    }
    payload = {
        "q": "",
        "numberOfResults": 20,
        "sortCriteria": "@date descending",
        "fieldsToInclude": ["title", "date", "excerpt", "clickUri"],
        "aq": f'@source=="משרד התחבורה" AND @date>="{date_str}"',
        "locale": "he"
    }

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        if r.status_code == 200:
            for item in r.json().get("results", []):
                articles.append({
                    "title": item.get("title", "ללא כותרת"),
                    "summary": item.get("excerpt", "")[:250],
                    "link": item.get("clickUri", "https://www.gov.il/he/departments/ministry_of_transport_and_road_safety"),
                    "source": "משרד התחבורה — gov.il"
                })
    except Exception as e:
        print(f"שגיאה בשליפת gov.il: {e}")

    return articles

def build_email(news_articles, mot_articles):
    date_str = (datetime.now() - timedelta(days=1)).strftime("%d/%m/%Y")

    html = f"""
    <html><body dir="rtl" style="font-family: Arial; max-width: 700px; margin: auto; direction: rtl;">
    <h2 style="color: #1a365d; border-bottom: 3px solid #2b6cb0; padding-bottom: 10px;">
      📰 סיכום תחבורה יומי — {date_str}
    </h2>

    <div style="background:#ebf8ff; border-radius:8px; padding:16px; margin-bottom:24px;">
      <h3 style="color:#2b6cb0; margin-top:0;">🏛️ הודעות משרד התחבורה</h3>
    """

    if mot_articles:
        for i, a in enumerate(mot_articles, 1):
            html += f"""
            <div style="background:white; border-radius:6px; padding:12px; margin-bottom:10px; border-right:4px solid #2b6cb0;">
              <strong>{i}. {a['title']}</strong><br>
              <span style="color:#555; font-size:0.9em;">{a['summary']}</span><br>
              <a href="{a['link']}" style="color:#2b6cb0; font-size:0.85em;">קרא עוד ←</a>
            </div>"""
    else:
        html += '<p style="color:#888;">לא נמצאו הודעות חדשות מהמשרד היום.</p>'

    html += f"""
    </div>
    <div style="background:#f0fff4; border-radius:8px; padding:16px; margin-bottom:24px;">
      <h3 style="color:#276749; margin-top:0;">📡 כתבות תעבורה מהתקשורת ({len(news_articles)} כתבות)</h3>
    """

    if news_articles:
        for i, a in enumerate(news_articles, 1):
            html += f"""
            <div style="background:white; border-radius:6px; padding:12px; margin-bottom:10px; border-right:4px solid #38a169;">
              <strong>{i}. {a['title']}</strong><br>
              <span style="color:#555; font-size:0.9em;">{a['summary']}</span><br>
              <a href="{a['link']}" style="color:#276749; font-size:0.85em;">קרא עוד ←</a>
              <small style="color:#999;"> — {a['source']}</small>
            </div>"""
    else:
        html += '<p style="color:#888;">לא נמצאו כתבות היום.</p>'

    html += "</div></body></html>"
    return html

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

if __name__ == "__main__":
    print("📥 שולף חדשות תעבורה...")
    news_articles = fetch_news_articles()

    print("🏛️ שולף הודעות משרד התחבורה...")
    mot_articles = fetch_mot_announcements()

    print(f"נמצאו: {len(news_articles)} חדשות + {len(mot_articles)} הודעות משרד")

    if news_articles or mot_articles:
        html = build_email(news_articles, mot_articles)
        send_email(html)
    else:
        print("לא נמצא תוכן היום")
