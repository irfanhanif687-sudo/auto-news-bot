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
GEMINI_API_KEY = "AIzaSyD8ngtXOVMv0zMzu_ULQPVC2NZoBIxJyyY"
PEXELS_API_KEY = "u6bM6qc8OrJn3i4hLakLPVnHduO1KsSoguJExJRZcaOMUmhR7xAYZ8A9"
# ==============================

# Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

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
    except Exception as e:
        print(f"      ⚠️ Image error: {e}")
    
    if len(images) < 2:
        fallback_images = [
            'https://images.pexels.com/photos/6071605/pexels-photo-6071605.jpeg',
            'https://images.pexels.com/photos/1181467/pexels-photo-1181467.jpeg'
        ]
        for i, img_url in enumerate(fallback_images[:2]):
            images.append({
                'url': img_url,
                'alt': f"News image {i+1}",
                'caption': title[:50],
                'credit': 'Pexels'
            })
    
    return images[:2]

def write_human_article(title, description, source, retry=0):
    """Write human-sounding article using Gemini 2.5 Flash"""
    current_date = datetime.now().strftime("%B %d, %Y")
    
    prompt = f"""Write a news article that sounds like a real human journalist wrote it.

TITLE: {title}
DATE: {current_date}
SOURCE: {source}
BACKGROUND: {description[:500]}

RULES:
- Write 2000-2500 words
- Sound NATURAL, like a person telling a story
- Use CONVERSATIONAL language
- Add REALISTIC quotes from witnesses or experts
- Write SHORT paragraphs (2-4 sentences)
- START with a strong opening
- END naturally
- NO placeholders like [LOCATION]
- NO generic phrases like "major developing story"

Write the complete article now in a natural, human voice:"""

    try:
        print(f"   ✍️ Writing article (attempt {retry + 1})...")
        response = model.generate_content(prompt)
        article = response.text
        
        word_count = len(article.split())
        print(f"   📊 Word count: {word_count}")
        
        if word_count < 1500 and retry < 2:
            print(f"   ⚠️ Too short, retrying...")
            time.sleep(5)
            return write_human_article(title, description, source, retry + 1)
        
        return article
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        if retry < 2:
            print(f"   🔄 Retrying...")
            time.sleep(10)
            return write_human_article(title, description, source, retry + 1)
        
        return f"<p><strong>{title}</strong></p><p>{description}</p>"

def post_to_blogger(service, title, content, images, source):
    current_date = datetime.now().strftime("%B %d, %Y")
    word_count = len(content.split())
    reading_time = max(10, round(word_count / 200))
    clean_title = title.replace('<', '&lt;').replace('>', '&gt;')
    
    slug = re.sub(r'[^a-z0-9]+', '-', clean_title.lower())[:60]
    current_url = f"https://newnews4public.blogspot.com/{datetime.now().year}/{datetime.now().month}/{slug}.html"
    
    images_html = ""
    for img in images:
        images_html += f'''
        <figure style="text-align: center; margin: 25px 0;">
            <img src="{img['url']}" alt="{img['alt'][:80]}" style="width:100%; max-width:750px; border-radius:12px; box-shadow:0 2px 8px rgba(0,0,0,0.1);" loading="lazy">
            <figcaption style="font-size:12px; color:#666; margin-top:8px;">📷 {img['caption'][:80]}</figcaption>
        </figure>
        '''
    
    content_html = content.replace('\n\n', '</p><p>')
    content_html = f'<p>{content_html}</p>'
    content_html = content_html.replace('<p><h2>', '<h2>').replace('</h2></p>', '</h2>')
    content_html = content_html.replace('<p><h3>', '<h3>').replace('</h3></p>', '</h3>')
    content_html = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', content_html)
    
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
    <meta name="twitter:card" content="summary_large_image">
    
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: 'Georgia', 'Times New Roman', serif; 
            max-width: 850px; 
            margin: 0 auto; 
            padding: 20px; 
            line-height: 1.75; 
            font-size: 18px; 
            color: #1a1a1a; 
            background: #fff; 
        }}
        h1 {{ 
            font-size: 38px; 
            line-height: 1.3; 
            margin-bottom: 15px; 
            color: #000; 
            font-weight: bold;
        }}
        h2 {{ 
            font-size: 28px; 
            margin: 40px 0 20px 0; 
            border-bottom: 3px solid #1a73e8; 
            padding-bottom: 8px; 
            color: #000; 
        }}
        .meta {{ 
            color: #666; 
            font-size: 13px; 
            margin-bottom: 25px; 
            padding-bottom: 15px; 
            border-bottom: 1px solid #e0e0e0; 
            display: flex; 
            justify-content: space-between; 
            flex-wrap: wrap; 
        }}
        .article-content p {{ 
            margin-bottom: 22px; 
            text-align: justify; 
            line-height: 1.75; 
        }}
        .article-content h2 {{ margin-top: 35px; }}
        hr {{ 
            margin: 40px 0; 
            border: none; 
            height: 1px; 
            background: linear-gradient(to right, transparent, #ccc, transparent); 
        }}
        @media (max-width: 600px) {{ 
            body {{ padding: 15px; font-size: 16px; }} 
            h1 {{ font-size: 28px; }} 
            h2 {{ font-size: 22px; }} 
        }}
    </style>
</head>
<body>

<h1>{clean_title}</h1>

<div class="meta">
    <span>📅 {current_date}</span>
    <span>📖 {reading_time} min read</span>
    <span>📰 {source}</span>
    <span>🔥 In-Depth</span>
</div>

{images_html}

<div class="article-content">
    {content_html}
</div>

<hr>

<div style="text-align: center; margin: 30px 0;">
    <div style="display: flex; justify-content: center; gap: 12px; flex-wrap: wrap;">
        <a href="https://twitter.com/intent/tweet?text={quote(clean_title[:70])}&url={quote(current_url)}" target="_blank" style="background:#1DA1F2; color:white; padding:10px 20px; border-radius:30px; text-decoration:none;">🐦 Share</a>
        <a href="https://www.facebook.com/sharer/sharer.php?u={quote(current_url)}" target="_blank" style="background:#4267B2; color:white; padding:10px 20px; border-radius:30px; text-decoration:none;">📘 Share</a>
        <a href="https://wa.me/?text={quote(clean_title[:50] + ' ' + current_url)}" target="_blank" style="background:#25D366; color:white; padding:10px 20px; border-radius:30px; text-decoration:none;">💬 Share</a>
    </div>
</div>

<div style="text-align: center; font-size: 12px; color: #999;">
    <p>© {datetime.now().year} News Analysis | In-Depth Coverage</p>
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
    ║         📰 HUMANISED NEWS BOT - GEMINI 2.5 FLASH                    ║
    ║                                                                      ║
    ║   ✓ 2000-2500 words per article                                     ║
    ║   ✓ NATURAL, human-sounding language                                ║
    ║   ✓ 2 relevant images per post                                      ║
    ║   ✓ Text justified | No errors                                      ║
    ║   ✓ 100% FREE                                                       ║
    ╚══════════════════════════════════════════════════════════════════════╝
    """)
    
    print("✅ Bot is RUNNING")
    print("📝 Writing humanised articles\n")
    
    articles = fetch_news()
    if not articles:
        print("   📭 No new stories")
        return
    
    processed = load_processed()
    
    for article in articles:
        story_id = article['title'][:80]
        if story_id in processed:
            continue
        
        print(f"\n📰 {article['title'][:70]}...")
        images = get_images(article['title'])
        content = write_human_article(article['title'], article.get('description', ''), article['source'])
        
        word_count = len(content.split())
        print(f"   📝 {word_count} words")
        
        service = google_login()
        if service:
            post_to_blogger(service, article['title'], content, images, article['source'])
            processed.add(story_id)
            save_processed(processed)
        
        break

if __name__ == "__main__":
    run()
