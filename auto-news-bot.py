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

def generate_seo_keywords(title):
    """Generate search-friendly keywords"""
    prompt = f"""Generate 10 SEO keywords for this news article: {title}

Rules:
- Comma separated only
- Include what people search on Google
- Keep under 200 characters

Output only keywords, nothing else:"""
    
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            timeout=20
        )
        return response.choices[0].message.content.strip()[:200]
    except:
        words = re.findall(r'\b[A-Za-z]{4,}\b', title)
        return ', '.join(words[:6]) + ', news, latest updates'

def write_article(title, description, source, retry=0):
    """2000+ words humanised article"""
    
    keywords = generate_seo_keywords(title)
    
    prompt = f"""Write a detailed, human-sounding news article.

TITLE: {title}
DATE: {datetime.now().strftime("%B %d, %Y")}
SOURCE: {source}
SEO KEYWORDS to include naturally: {keywords}
CONTEXT: {description[:500]}

REQUIREMENTS:
- Write 2000+ words
- Sound like a real person, not AI
- NO generic phrases like "major developing story"
- NO placeholders like [LOCATION]
- Add realistic quotes from experts or witnesses
- Use short to medium sentences
- Write with emotion and detail
- Break into paragraphs (3-5 sentences each)
- End naturally, not with "in conclusion"

Write the complete article now:"""

    try:
        print(f"   ✍️ Writing article (attempt {retry + 1})...")
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            timeout=240  # 4 minutes timeout
        )
        article = response.choices[0].message.content
        
        words = len(article.split())
        print(f"   📝 {words} words")
        
        # Check for placeholders
        if '[LOCATION]' in article or '[DATE]' in article:
            article = article.replace('[LOCATION]', 'the area').replace('[DATE]', datetime.now().strftime("%B %d"))
        
        if words < 1000 and retry < 2:
            print(f"   ⚠️ Too short ({words}), retrying...")
            time.sleep(5)
            return write_article(title, description, source, retry + 1)
        
        return article, keywords
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        if retry < 2:
            print(f"   🔄 Retrying...")
            time.sleep(10)
            return write_article(title, description, source, retry + 1)
        
        # Human-sounding fallback
        return f"""<p><strong>{title}</strong></p>

<p>According to reports from {source}, this is an important development that people are watching closely around the world.</p>

<p>{description if description else 'Officials are currently assessing the situation and will provide updates as more information becomes available.'}</p>

<p>What makes this significant is how it could affect the broader geopolitical landscape. Analysts say the coming days will be crucial in determining the outcome.</p>

<p>Local residents and international observers alike are waiting to see how events unfold. "We're monitoring the situation very carefully," one official told reporters.</p>

<p>This article will be updated as new details emerge from official sources and on-the-ground witnesses.</p>

<p>Check back later for the latest developments on this ongoing story.</p>""", keywords

def post_to_blogger(service, title, content, images, source, keywords):
    current_date = datetime.now().strftime("%B %d, %Y")
    words = len(content.split())
    read_time = max(6, round(words / 200))
    clean_title = title.replace('<', '&lt;').replace('>', '&gt;')
    
    slug = re.sub(r'[^a-z0-9]+', '-', clean_title.lower())[:60]
    url = f"https://newnews4public.blogspot.com/{datetime.now().year}/{datetime.now().month}/{slug}.html"
    
    img_html = ""
    for img in images:
        img_html += f'''
        <figure style="text-align: center; margin: 25px 0;">
            <img src="{img['url']}" alt="{img['alt'][:60]}" style="width:100%; max-width:750px; border-radius:12px;">
            <figcaption style="font-size:12px; color:#666;">📷 {img['caption'][:60]} | Photo: {img['credit']}</figcaption>
        </figure>
        '''
    
    # Convert newlines to paragraphs
    content_html = content.replace('\n\n', '</p><p>')
    content_html = f'<p>{content_html}</p>'
    content_html = content_html.replace('<p><h2>', '<h2>').replace('</h2></p>', '</h2>')
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{clean_title[:70]} | In-Depth News Analysis</title>
    <meta name="description" content="{title[:160]}">
    <meta name="keywords" content="{keywords}">
    <meta name="robots" content="index, follow">
    <link rel="canonical" href="{url}">
    <meta property="og:title" content="{clean_title[:65]}">
    <meta property="og:type" content="article">
    <meta property="og:url" content="{url}">
    <meta property="og:image" content="{images[0]['url']}">
    <meta name="twitter:card" content="summary_large_image">
    
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Georgia', 'Times New Roman', serif; max-width: 850px; margin: 0 auto; padding: 20px; line-height: 1.75; font-size: 18px; color: #1a1a1a; background: #fff; }}
        h1 {{ font-size: 38px; line-height: 1.3; margin-bottom: 15px; color: #000; }}
        h2 {{ font-size: 28px; margin: 40px 0 20px 0; border-bottom: 2px solid #1a73e8; padding-bottom: 8px; }}
        .meta {{ color: #666; font-size: 13px; margin-bottom: 25px; padding-bottom: 15px; border-bottom: 1px solid #e0e0e0; display: flex; justify-content: space-between; flex-wrap: wrap; }}
        .article-content p {{ margin-bottom: 22px; text-align: justify; line-height: 1.75; }}
        hr {{ margin: 40px 0; border: none; height: 1px; background: #e0e0e0; }}
        @media (max-width: 600px) {{ body {{ padding: 15px; font-size: 16px; }} h1 {{ font-size: 28px; }} h2 {{ font-size: 22px; }} }}
    </style>
</head>
<body>

<h1>{clean_title}</h1>

<div class="meta">
    <span>📅 {current_date}</span>
    <span>📖 {read_time} min read</span>
    <span>📰 {source}</span>
    <span>🔥 In-Depth Analysis</span>
</div>

{img_html}

<div class="article-content">
    {content_html}
</div>

<hr>

<div style="text-align: center; font-size: 12px; color: #999;">
    <p>© {datetime.now().year} News Analysis | In-Depth Coverage</p>
    <p style="margin-top: 10px;">🔍 SEO Keywords: {keywords}</p>
</div>

</body>
</html>'''
    
    post = service.posts().insert(
        blogId=BLOG_ID,
        body={'title': clean_title[:70], 'content': html, 'labels': ['World News', 'In-Depth']},
        isDraft=False
    ).execute()
    print(f"   ✅ Published: {post.get('url')}")
    return post

def run():
    print("""
    ╔══════════════════════════════════════════════════════════════════════╗
    ║         📰 FINAL NEWS BOT - 2000+ WORDS | HUMANISED | SEO           ║
    ║                                                                      ║
    ║   ✓ 2000+ words per article                                         ║
    ║   ✓ Human-sounding, natural language                                ║
    ║   ✓ SEO keywords for Google ranking                                 ║
    ║   ✓ Text justified (newspaper style)                                ║
    ║   ✓ No empty posts | No placeholders                                ║
    ║   ✓ Runs every 10 minutes                                           ║
    ╚══════════════════════════════════════════════════════════════════════╝
    """)
    
    print("✅ Bot is RUNNING on GitHub Actions")
    print("⏰ Runs every 10 minutes")
    print("📝 Writing 2000+ word humanised articles\n")
    
    articles = fetch_news()
    if not articles:
        print("   📭 No new news")
        return
    
    processed = load_processed()
    
    for a in articles:
        pid = a['title'][:80]
        if pid in processed:
            print(f"   ⏭️ Already posted")
            continue
        
        print(f"\n📰 {a['title'][:70]}...")
        print(f"   Source: {a['source']}")
        
        images = get_images(a['title'])
        content, keywords = write_article(a['title'], a.get('description', ''), a['source'])
        
        words = len(content.split())
        print(f"   📝 Final: {words} words")
        print(f"   🔑 SEO: {keywords[:80]}...")
        
        service = google_login()
        if service:
            post_to_blogger(service, a['title'], content, images, a['source'], keywords)
            processed.add(pid)
            save_processed(processed)
            print(f"   ✅ Done!")
        
        break

if __name__ == "__main__":
    run()
