import requests
import feedparser
import time
import os
import json
import re
from datetime import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from urllib.parse import quote

# ========== SETTINGS ==========
BLOG_ID = "4233785800723613713"
OPENROUTER_API_KEY = "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"
PEXELS_API_KEY = "u6bM6qc8OrJn3i4hLakLPVnHduO1KsSoguJExJRZcaOMUmhR7xAYZ8A9"
# ==============================

PROCESSED_FILE = "processed_news.json"

def load_processed():
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, 'r') as f:
            return set(json.load(f))
    return set()

def save_processed(data):
    with open(PROCESSED_FILE, 'w') as f:
        json.dump(list(data), f)

def google_login():
    SCOPES = ['https://www.googleapis.com/auth/blogger']
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                print("❌ credentials.json missing!")
                return None
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('blogger', 'v3', credentials=creds)

RSS_FEEDS = [
    'http://feeds.bbci.co.uk/news/world/rss.xml',
    'https://www.aljazeera.com/xml/rss/all.xml',
]

def fetch_news():
    articles = []
    processed = load_processed()
    print(f"   📡 Checking feeds...")
    
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            source_name = feed.feed.get('title', 'Unknown')[:30]
            
            for entry in feed.entries[:3]:
                title = entry.get('title', '').strip()
                link = entry.get('link', '')
                description = entry.get('summary', '')[:500]
                description = re.sub(r'<[^>]+>', '', description)
                
                if title and link and len(title) > 25:
                    story_id = title[:80]
                    if story_id not in processed:
                        articles.append({
                            'title': title,
                            'url': link,
                            'description': description,
                            'source': source_name,
                        })
        except Exception as e:
            print(f"      ⚠️ Error: {e}")
    
    seen = set()
    unique = []
    for a in articles:
        if a['title'] not in seen:
            seen.add(a['title'])
            unique.append(a)
    
    print(f"   ✅ Found {len(unique)} new stories")
    return unique[:1]

def get_images(title):
    images = []
    keywords = ' '.join(title.split()[:5])
    
    try:
        url = f"https://api.pexels.com/v1/search?query={quote(keywords)}&per_page=4&orientation=landscape"
        headers = {"Authorization": PEXELS_API_KEY}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            photos = data.get('photos', [])
            for i, photo in enumerate(photos[:2]):
                images.append({
                    'url': photo['src']['large'],
                    'alt': f"{title[:50]} - image {i+1}",
                    'caption': f"{title[:60]} | Credit: {photo.get('photographer', 'Pexels')}",
                    'credit': photo.get('photographer', 'Pexels')
                })
    except:
        pass
    
    if len(images) < 2:
        fallback = [
            'https://images.pexels.com/photos/6071605/pexels-photo-6071605.jpeg',
            'https://images.pexels.com/photos/1181467/pexels-photo-1181467.jpeg'
        ]
        for i, img_url in enumerate(fallback[:2]):
            images.append({'url': img_url, 'alt': f"News image {i+1}", 'caption': title[:50], 'credit': 'Pexels'})
    
    return images[:2]

def write_article(title, description, source, retry=0):
    current_date = datetime.now().strftime("%B %d, %Y")
    
    prompt = f"""Write a complete, human-sounding news article.

TITLE: {title}
DATE: {current_date}
SOURCE: {source}
CONTEXT: {description[:500]}

REQUIREMENTS:
- Write 1500-2000 words
- Sound like a real journalist
- Add realistic quotes from witnesses or experts
- Use short paragraphs (2-4 sentences)
- NO placeholders
- Strong opening, natural ending

Write the complete article now:"""

    try:
        print(f"   ✍️ Writing article via OpenRouter (Gemini 2.0 Flash)...")
        
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "google/gemini-2.0-flash-exp:free",  # Changed model
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 8000,
            },
            timeout=240
        )
        
        if response.status_code == 200:
            article = response.json()['choices'][0]['message']['content']
            word_count = len(article.split())
            print(f"   📊 {word_count} words")
            
            if word_count < 500 and retry < 2:
                print(f"   ⚠️ Too short, retrying...")
                time.sleep(5)
                return write_article(title, description, source, retry + 1)
            
            return article
        else:
            print(f"   ❌ API Error: {response.status_code}")
            print(f"   Response: {response.text[:200]}")
            if retry < 2:
                time.sleep(5)
                return write_article(title, description, source, retry + 1)
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
        if retry < 2:
            time.sleep(5)
            return write_article(title, description, source, retry + 1)
    
    return f"<p><strong>{title}</strong></p><p>{description}</p>"

def post_to_blogger(service, title, content, images, source):
    current_date = datetime.now().strftime("%B %d, %Y")
    word_count = len(content.split())
    reading_time = max(8, round(word_count / 200))
    clean_title = title.replace('<', '&lt;').replace('>', '&gt;')
    
    slug = re.sub(r'[^a-z0-9]+', '-', clean_title.lower())[:60]
    current_url = f"https://newnews4public.blogspot.com/{datetime.now().year}/{datetime.now().month}/{slug}.html"
    
    images_html = ""
    for img in images:
        images_html += f'<img src="{img["url"]}" style="width:100%; margin:15px 0; border-radius:10px;">'
    
    content_html = content.replace('\n\n', '</p><p>')
    content_html = f'<p>{content_html}</p>'
    content_html = content_html.replace('<p><h2>', '<h2>').replace('</h2></p>', '</h2>')
    
    html = f'''<!DOCTYPE html>
<html>
<head>
    <title>{clean_title[:70]} | News Analysis</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="description" content="{title[:160]}">
    <link rel="canonical" href="{current_url}">
    <style>
        body {{ font-family: 'Georgia', 'Times New Roman', serif; max-width: 800px; margin: 0 auto; padding: 20px; line-height: 1.7; font-size: 18px; color: #1a1a1a; }}
        h1 {{ font-size: 36px; margin-bottom: 15px; }}
        h2 {{ font-size: 28px; margin: 35px 0 15px 0; border-bottom: 2px solid #1a73e8; padding-bottom: 8px; }}
        .meta {{ color: #666; font-size: 13px; margin-bottom: 25px; border-bottom: 1px solid #e0e0e0; padding-bottom: 15px; }}
        p {{ text-align: justify; margin-bottom: 22px; line-height: 1.7; }}
        hr {{ margin: 40px 0; border: none; height: 1px; background: #e0e0e0; }}
        @media (max-width: 600px) {{ body {{ padding: 15px; font-size: 16px; }} h1 {{ font-size: 28px; }} h2 {{ font-size: 22px; }} }}
    </style>
</head>
<body>
    <h1>{clean_title}</h1>
    <div class="meta">
        <span>📅 {current_date}</span>
        <span>📖 {reading_time} min read</span>
        <span>📰 {source}</span>
    </div>
    {images_html}
    <div class="content">
        {content_html}
    </div>
    <hr>
    <p style="text-align: center; font-size: 12px; color: #999;">© {datetime.now().year} News Analysis | In-Depth Coverage</p>
</body>
</html>'''
    
    post = service.posts().insert(
        blogId=BLOG_ID,
        body={'title': clean_title[:70], 'content': html},
        isDraft=False
    ).execute()
    print(f"   ✅ Published: {post.get('url')}")
    return post

def run():
    print("""
    ╔══════════════════════════════════════════════════════════════════════╗
    ║      📰 OPENROUTER NEWS BOT - GEMINI 2.0 FLASH                      ║
    ║                                                                      ║
    ║   ✓ Gemini 2.0 Flash (fast & reliable)                              ║
    ║   ✓ 1500-2000 words humanised articles                              ║
    ║   ✓ 2 images from Pexels                                            ║
    ║   ✓ Text justified | No errors                                      ║
    ║   ✓ NO credit card required                                         ║
    ╚══════════════════════════════════════════════════════════════════════╝
    """)
    
    print("✅ Bot is RUNNING")
    print("📝 Writing articles via Gemini 2.0 Flash\n")
    
    articles = fetch_news()
    if not articles:
        print("📭 No new stories")
        return
    
    processed = load_processed()
    
    for a in articles:
        pid = a['title'][:80]
        if pid in processed:
            continue
        
        print(f"\n📰 {a['title'][:60]}...")
        images = get_images(a['title'])
        content = write_article(a['title'], a.get('description', ''), a['source'])
        
        service = google_login()
        if service:
            post_to_blogger(service, a['title'], content, images, a['source'])
            processed.add(pid)
            save_processed(processed)
        break

if __name__ == "__main__":
    run()
