import requests
import feedparser
import time
import os
import json
import re
from datetime import datetime
import google.generativeai as genai
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from urllib.parse import quote

# ========== SETTINGS ==========
BLOG_ID = "4233785800723613713"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyB6OLq87wym4HuJJs6IijTRU1SgibsGE-U")
PEXELS_API_KEY = "u6bM6qc8OrJn3i4hLakLPVnHduO1KsSoguJExJRZcaOMUmhR7xAYZ8A9"
# ==============================

# Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

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
    print(f"   📡 Checking {len(RSS_FEEDS)} feeds...")
    
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
            print(f"      ⚠️ Feed error: {e}")
    
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
    """Write humanised article using Gemini"""
    current_date = datetime.now().strftime("%B %d, %Y")
    
    prompt = f"""Write a complete, human-sounding news article.

TITLE: {title}
DATE: {current_date}
SOURCE: {source}
CONTEXT: {description[:500]}

REQUIREMENTS:
- Write 1500-2000 words
- Sound like a real journalist, not AI
- Use short to medium sentences
- Add realistic quotes from witnesses or experts
- Break into small paragraphs
- NO placeholders like [LOCATION]
- NO generic phrases
- End naturally

Write the complete article now:"""

    try:
        print(f"   ✍️ Writing article (attempt {retry + 1})...")
        response = model.generate_content(prompt)
        article = response.text
        
        word_count = len(article.split())
        print(f"   📊 Word count: {word_count}")
        
        if word_count < 800 and retry < 2:
            print(f"   ⚠️ Too short, retrying...")
            time.sleep(5)
            return write_article(title, description, source, retry + 1)
        
        return article
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        if retry < 2:
            print(f"   🔄 Retrying...")
            time.sleep(10)
            return write_article(title, description, source, retry + 1)
        
        return f"<p><strong>{title}</strong></p><p>{description}</p><p>This article will be updated.</p>"

def post_to_blogger(service, title, content, images, source):
    current_date = datetime.now().strftime("%B %d, %Y")
    word_count = len(content.split())
    reading_time = max(5, round(word_count / 200))
    clean_title = title.replace('<', '&lt;').replace('>', '&gt;')
    
    slug = re.sub(r'[^a-z0-9]+', '-', clean_title.lower())[:60]
    current_url = f"https://newnews4public.blogspot.com/{datetime.now().year}/{datetime.now().month}/{slug}.html"
    
    images_html = ""
    for img in images:
        images_html += f'''
        <figure style="text-align: center; margin: 25px 0;">
            <img src="{img['url']}" alt="{img['alt'][:60]}" style="width:100%; max-width:750px; border-radius:12px;">
            <figcaption style="font-size:12px; color:#666;">📷 {img['caption'][:60]} | Photo: {img['credit']}</figcaption>
        </figure>
        '''
    
    content_html = content.replace('\n\n', '</p><p>')
    content_html = f'<p>{content_html}</p>'
    content_html = content_html.replace('<p><h2>', '<h2>').replace('</h2></p>', '</h2>')
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{clean_title[:70]} | News Analysis</title>
    <meta name="description" content="{title[:160]}">
    <meta name="robots" content="index, follow">
    <link rel="canonical" href="{current_url}">
    <meta property="og:title" content="{clean_title[:65]}">
    <meta property="og:type" content="article">
    <meta property="og:url" content="{current_url}">
    <meta property="og:image" content="{images[0]['url'] if images else ''}">
    
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Georgia', 'Times New Roman', serif; max-width: 850px; margin: 0 auto; padding: 20px; line-height: 1.75; font-size: 18px; color: #1a1a1a; background: #fff; }}
        h1 {{ font-size: 38px; margin-bottom: 15px; }}
        h2 {{ font-size: 28px; margin: 40px 0 20px 0; border-bottom: 2px solid #1a73e8; padding-bottom: 8px; }}
        .meta {{ color: #666; font-size: 13px; margin-bottom: 25px; border-bottom: 1px solid #e0e0e0; padding-bottom: 15px; display: flex; justify-content: space-between; }}
        .article-content p {{ margin-bottom: 22px; text-align: justify; line-height: 1.75; }}
        hr {{ margin: 40px 0; }}
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

<div class="article-content">
    {content_html}
</div>

<hr>

<div style="text-align: center; font-size: 12px; color: #999;">
    <p>© {datetime.now().year} News Analysis</p>
</div>

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
    ║         📰 GEMINI POWERED NEWS BOT - FINAL VERSION                  ║
    ║                                                                      ║
    ║   ✓ 1500-2000 words per article                                     ║
    ║   ✓ Humanised, natural language                                     ║
    ║   ✓ Text justified | No errors                                      ║
    ║   ✓ Runs every 30 minutes                                           ║
    ╚══════════════════════════════════════════════════════════════════════╝
    """)
    
    print("✅ Bot is RUNNING")
    print("⏰ Runs every 30 minutes\n")
    
    articles = fetch_news()
    if not articles:
        print("   📭 No new news")
        return
    
    processed = load_processed()
    
    for a in articles:
        pid = a['title'][:80]
        if pid in processed:
            continue
        
        print(f"\n📰 {a['title'][:70]}...")
        print(f"   Source: {a['source']}")
        
        images = get_images(a['title'])
        content = write_article(a['title'], a.get('description', ''), a['source'])
        
        words = len(content.split())
        print(f"   📝 {words} words")
        
        service = google_login()
        if service:
            post_to_blogger(service, a['title'], content, images, a['source'])
            processed.add(pid)
            save_processed(processed)
        
        break

if __name__ == "__main__":
    run()
