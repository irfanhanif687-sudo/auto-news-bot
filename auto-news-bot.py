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

# ========== SETTINGS ==========
BLOG_ID = "4233785800723613713"
GROQ_API_KEY = "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"
PEXELS_API_KEY = "u6bM6qc8OrJn3i4hLakLPVnHduO1KsSoguJExJRZcaOMUmhR7xAYZ8A9"
# ==============================

client = Groq(api_key=GROQ_API_KEY)
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
    'http://feeds.bbci.co.uk/news/business/rss.xml',
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
    keywords = ' '.join(title.split()[:4])
    
    try:
        url = f"https://api.pexels.com/v1/search?query={quote(keywords)}&per_page=2&orientation=landscape"
        headers = {"Authorization": PEXELS_API_KEY}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            photos = data.get('photos', [])
            for photo in photos[:2]:
                images.append({
                    'url': photo['src']['large'],
                    'alt': title[:60],
                    'caption': title[:60],
                    'credit': photo.get('photographer', 'Pexels')
                })
    except:
        pass
    
    if not images:
        images.append({
            'url': 'https://images.pexels.com/photos/6071605/pexels-photo-6071605.jpeg',
            'alt': 'News image',
            'caption': title[:50],
            'credit': 'Pexels'
        })
    
    return images

def write_article(title, description, source, retry=0):
    """Simple human article writer - no bakwas"""
    
    prompt = f"""Write a detailed news article in a natural, human tone.

TITLE: {title}
DATE: {datetime.now().strftime("%B %d, %Y")}
SOURCE: {source}
DETAILS: {description[:500]}

IMPORTANT RULES:
- Write like a real person, not AI
- Minimum 1500 words
- NO generic phrases like "major developing story"
- NO placeholders like [LOCATION]
- Use short sentences
- Add real-sounding quotes
- Be specific and detailed
- Write with emotion where appropriate
- End naturally

Write the article now:"""

    try:
        print(f"   ✍️ Writing article...")
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            timeout=180
        )
        article = response.choices[0].message.content
        
        words = len(article.split())
        print(f"   📝 {words} words")
        
        if words < 800 and retry < 2:
            print(f"   ⚠️ Too short ({words}), retrying...")
            time.sleep(5)
            return write_article(title, description, source, retry + 1)
        
        return article
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        if retry < 2:
            print(f"   🔄 Retrying...")
            time.sleep(10)
            return write_article(title, description, source, retry + 1)
        
        # Simple fallback - no bakwas
        return f"""<p><strong>{title}</strong></p>

<p>According to reports from {source}, this story is developing. Here's what we know based on information currently available.</p>

<p>{description if description else 'Officials are investigating the situation and will provide updates as more information becomes available.'}</p>

<p>This article will be updated as new details emerge from official sources and witnesses on the ground.</p>"""

def post_to_blogger(service, title, content, images, source):
    current_date = datetime.now().strftime("%B %d, %Y")
    words = len(content.split())
    read_time = max(5, round(words / 200))
    clean_title = title.replace('<', '&lt;').replace('>', '&gt;')
    
    slug = re.sub(r'[^a-z0-9]+', '-', clean_title.lower())[:60]
    url = f"https://newnews4public.blogspot.com/{datetime.now().year}/{datetime.now().month}/{slug}.html"
    
    img_html = ""
    for img in images:
        img_html += f'<img src="{img["url"]}" alt="{img["alt"][:60]}" style="width:100%; max-width:700px; margin:20px 0; border-radius:10px;">'
    
    html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{clean_title[:70]} | News Analysis</title>
    <meta name="description" content="{title[:160]}">
    <link rel="canonical" href="{url}">
    <style>
        body {{ font-family: Georgia, serif; max-width: 800px; margin: 0 auto; padding: 20px; line-height: 1.7; font-size: 18px; }}
        h1 {{ font-size: 36px; margin-bottom: 15px; }}
        .meta {{ color: #666; font-size: 13px; margin-bottom: 25px; border-bottom: 1px solid #eee; padding-bottom: 15px; }}
        .content p {{ margin-bottom: 22px; text-align: justify; }}
        hr {{ margin: 40px 0; }}
        @media (max-width: 600px) {{ body {{ padding: 15px; font-size: 16px; }} h1 {{ font-size: 28px; }} }}
    </style>
</head>
<body>
    <h1>{clean_title}</h1>
    <div class="meta">📅 {current_date} | 📖 {read_time} min read | 📰 {source}</div>
    {img_html}
    <div class="content">{content.replace(chr(10), '</p><p>')}</div>
    <hr>
    <p style="text-align: center; font-size: 12px; color: #999;">© {datetime.now().year} News Analysis</p>
</body>
</html>'''
    
    post = service.posts().insert(blogId=BLOG_ID, body={'title': clean_title[:70], 'content': html}, isDraft=False).execute()
    print(f"   ✅ Published: {post.get('url')}")
    return post

def run():
    print("\n" + "="*50)
    print("📰 NEWS BOT - RUNNING")
    print("="*50)
    
    articles = fetch_news()
    if not articles:
        print("   No new news")
        return
    
    processed = load_processed()
    
    for a in articles:
        pid = a['title'][:80]
        if pid in processed:
            print(f"   Already posted: {a['title'][:50]}...")
            continue
        
        print(f"\n📰 {a['title'][:70]}...")
        print(f"   Source: {a['source']}")
        
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
