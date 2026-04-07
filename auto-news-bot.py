import requests
import feedparser
import time
import os
import json
import re
from datetime import datetime
from groq import Groq
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from urllib.parse import quote

# ================== SETTINGS ==================
BLOG_ID = "4233785800723613713"
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
PROCESSED_FILE = "processed_news.json"

client = Groq(api_key=GROQ_API_KEY)

RSS_FEEDS = [
    'http://feeds.bbci.co.uk/news/world/rss.xml',
    'http://feeds.bbci.co.uk/news/business/rss.xml',
    'https://www.aljazeera.com/xml/rss/all.xml',
]

# ================== STORAGE ==================
def load_processed():
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, 'r') as f:
            return set(json.load(f))
    return set()

def save_processed(data):
    with open(PROCESSED_FILE, 'w') as f:
        json.dump(list(data), f)

# ================== GOOGLE LOGIN ==================
def google_login():
    SCOPES = ['https://www.googleapis.com/auth/blogger']
    creds = None

    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)

        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    return build('blogger', 'v3', credentials=creds)

# ================== FETCH NEWS ==================
def fetch_news():
    articles = []
    processed = load_processed()

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        source = feed.feed.get('title', 'Unknown')

        for entry in feed.entries[:5]:
            title = entry.get('title', '').strip()
            link = entry.get('link', '')
            desc = re.sub(r'<[^>]+>', '', entry.get('summary', ''))[:400]

            story_id = str(hash(title + link))

            if title and story_id not in processed and len(title) > 30:
                articles.append({
                    'title': title,
                    'url': link,
                    'description': desc,
                    'source': source,
                    'id': story_id
                })

    return articles[:1]

# ================== IMAGES ==================
def get_images(title):
    try:
        url = f"https://api.pexels.com/v1/search?query={quote(title[:40])}&per_page=2"
        headers = {"Authorization": PEXELS_API_KEY}
        r = requests.get(url, headers=headers, timeout=10)

        photos = r.json().get('photos', [])
        return [{
            'url': p['src']['large'],
            'alt': f"{title[:50]} news image",
            'credit': p.get('photographer', 'Pexels')
        } for p in photos[:2]]

    except:
        return [{
            'url': 'https://images.pexels.com/photos/6071605/pexels-photo-6071605.jpeg',
            'alt': 'news image',
            'credit': 'Pexels'
        }]

# ================== SEO KEYWORDS ==================
def seo_keywords(title):
    words = re.findall(r'\b[A-Za-z]{4,}\b', title)
    return ', '.join(words[:6]) + ', latest news, world news'

# ================== ARTICLE WRITER ==================
def write_article(title, desc, source):
    prompt = f"""
Write a natural, human-like news article.

Title: {title}
Context: {desc}

Rules:
- 1200–1800 words
- Conversational tone
- No fake quotes or names
- Use headings (H2)
- Short paragraphs
- Add analysis naturally
- Avoid robotic tone

Start writing:
"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        timeout=180
    )

    return response.choices[0].message.content

# ================== HTML FORMAT ==================
def format_html(title, content, images, source, keywords):
    paragraphs = [f"<p>{p.strip()}</p>" for p in content.split("\n") if p.strip()]
    content_html = "".join(paragraphs)

    img_html = ""
    for img in images:
        img_html += f"""
        <img src="{img['url']}" alt="{img['alt']}" style="width:100%; margin:20px 0;">
        """

    return f"""
<h1>{title}</h1>
<p><b>Source:</b> {source} | {datetime.now().strftime('%B %d, %Y')}</p>

{img_html}

{content_html}

<hr>
<p><b>Keywords:</b> {keywords}</p>
"""

# ================== POST ==================
def post(service, title, html):
    return service.posts().insert(
        blogId=BLOG_ID,
        body={'title': title, 'content': html},
        isDraft=False
    ).execute()

# ================== MAIN ==================
def run():
    print("🚀 PRO NEWS BOT RUNNING")

    service = google_login()
    if not service:
        print("❌ Blogger login failed")
        return

    processed = load_processed()
    articles = fetch_news()

    if not articles:
        print("📭 No news")
        return

    for a in articles:
        print(f"📰 {a['title']}")

        images = get_images(a['title'])
        content = write_article(a['title'], a['description'], a['source'])
        keywords = seo_keywords(a['title'])

        html = format_html(a['title'], content, images, a['source'], keywords)

        post(service, a['title'], html)

        processed.add(a['id'])
        save_processed(processed)

        print("✅ Posted Successfully")
        time.sleep(5)
        break

if __name__ == "__main__":
    run()
