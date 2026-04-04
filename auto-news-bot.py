import requests
import feedparser
import time
import os
import json
import re
import signal
import sys
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
running = True

def signal_handler(sig, frame):
    global running
    print("\n\n🛑 Bot stopping gracefully...")
    running = False
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

RSS_FEEDS = [
    'http://feeds.bbci.co.uk/news/world/rss.xml',
    'https://www.aljazeera.com/xml/rss/all.xml',
]

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

def fetch_news():
    articles = []
    processed = load_processed()
    print("   📡 Checking RSS feeds...")
    
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:2]:
                title = entry.get('title', '').strip()
                link = entry.get('link', '')
                description = entry.get('summary', '')[:200]
                description = re.sub(r'<[^>]+>', '', description)
                
                if title and link and len(title) > 20:
                    story_id = title[:60]
                    if story_id not in processed:
                        source = feed.feed.get('title', 'News').split(' - ')[0][:25]
                        articles.append({
                            'title': title,
                            'url': link,
                            'description': description,
                            'source': source
                        })
        except Exception as e:
            print(f"   ⚠️ Feed error: {e}")
    
    seen = set()
    unique = []
    for a in articles:
        if a['title'] not in seen:
            seen.add(a['title'])
            unique.append(a)
    
    if unique:
        print(f"   ✅ Found {len(unique)} new stories")
    else:
        print(f"   📭 No new stories (checked {len(RSS_FEEDS)} feeds)")
    
    return unique[:2]

def get_images(title):
    images = []
    keywords = ' '.join(title.split()[:4])
    
    search_terms = [keywords, f"{keywords} scene", f"{keywords} view"]
    
    for i, term in enumerate(search_terms[:3]):
        try:
            url = f"https://api.pexels.com/v1/search?query={quote(term)}&per_page=3&orientation=landscape"
            headers = {"Authorization": PEXELS_API_KEY}
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                photos = data.get('photos', [])
                if photos:
                    photo = photos[0]
                    images.append({
                        'url': photo['src']['large'],
                        'alt': f"{title[:45]} - image {i+1}",
                        'caption': f"{title[:40]} - captured view",
                        'credit': photo.get('photographer', 'Pexels')
                    })
                    continue
        except:
            pass
        
        fallback = [
            ('https://images.pexels.com/photos/6071605/pexels-photo-6071605.jpeg', 'Global view', 'World news'),
            ('https://images.pexels.com/photos/1181467/pexels-photo-1181467.jpeg', 'Technology', 'Space tech'),
            ('https://images.pexels.com/photos/210607/pexels-photo-210607.jpeg', 'Mission', 'NASA facility')
        ]
        images.append({
            'url': fallback[i][0],
            'alt': fallback[i][1],
            'caption': fallback[i][2],
            'credit': 'Pexels'
        })
    
    return images

def extract_keywords(title):
    stop_words = {'a', 'an', 'the', 'and', 'of', 'to', 'in', 'for', 'on', 'with', 'by', 'is', 'are', 'was', 'were'}
    words = title.lower().split()
    keywords = [w for w in words if w not in stop_words and len(w) > 3]
    return ', '.join(keywords[:10])

def write_article(title, description):
    current_date = datetime.now().strftime("%B %d, %Y")
    keywords = extract_keywords(title)
    
    prompt = f"""Write a news article. Today is {current_date}.

TITLE: {title}
CONTEXT: {description}
KEYWORDS: {keywords}

STRUCTURE:

## Introduction
(2 paragraphs)

## Key Takeaways
- First takeaway
- Second takeaway
- Third takeaway
- Fourth takeaway
- Fifth takeaway

## Background
(2-3 paragraphs)

## Main Analysis
(3-4 paragraphs)

## Impact
(2 paragraphs)

## Frequently Asked Questions

**Q1: Question?**
Answer here.

**Q2: Question?**
Answer here.

**Q3: Question?**
Answer here.

## Conclusion
(2 paragraphs)

RULES:
- Write 1500-1800 words
- Each paragraph 2-3 sentences
- Blank line between paragraphs
- No placeholders

Write now:"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            timeout=120
        )
        article = response.choices[0].message.content
        article = re.sub(r'^#.*$', '', article, flags=re.MULTILINE)
        return article, keywords
    except Exception as e:
        print(f"   AI Error: {e}")
        return get_fallback(title, description), keywords

def get_fallback(title, description):
    return f"""<h2>Introduction</h2>
<p>{description if description else title}</p>

<h2>Key Takeaways</h2>
<ul><li>{title[:80]}</li><li>Major development</li></ul>

<h2>Analysis</h2>
<p>This story continues to develop.</p>

<h2>Conclusion</h2>
<p>Stay tuned for updates.</p>"""

def create_json_ld(title, description, keywords, current_url):
    return {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": title[:110],
        "description": description[:150] if description else title[:150],
        "keywords": keywords,
        "datePublished": datetime.now().strftime("%Y-%m-%d"),
        "author": {"@type": "Organization", "name": "News Analysis Team"},
        "publisher": {"@type": "Organization", "name": "News Analysis"}
    }

def post_to_blogger(service, title, content, images, source, keywords):
    current_date = datetime.now().strftime("%B %d, %Y")
    word_count = len(content.split())
    reading_time = max(6, round(word_count / 200))
    clean_title = title.replace('<', '&lt;').replace('>', '&gt;')
    
    slug = re.sub(r'[^a-z0-9]+', '-', clean_title.lower())[:50]
    current_url = f"https://newnews4public.blogspot.com/{datetime.now().year}/{datetime.now().month}/{slug}.html"
    
    images_html = ""
    for i, img in enumerate(images):
        images_html += f'''
        <div style="text-align: center; margin: 20px 0;">
            <img src="{img['url']}" alt="{img['alt'][:60]}" style="width:100%; max-width:650px; border-radius:8px;">
            <p style="font-size:11px; color:#666;">📷 Image {i+1}: {img['caption'][:55]} | Credit: {img['credit']}</p>
        </div>
        '''
    
    content_html = content.replace('\n\n', '</p><p>')
    content_html = f'<p>{content_html}</p>'
    content_html = content_html.replace('<p><h2>', '<h2>').replace('</h2></p>', '</h2>')
    content_html = content_html.replace('<p><ul>', '<ul>').replace('</ul></p>', '</ul>')
    content_html = content_html.replace('<p><li>', '<li>').replace('</li></p>', '</li>')
    content_html = re.sub(r'\*\*Q(\d+): (.*?)\*\*\s*\n', r'<div class="faq-q"><strong>❓ Q\1: \2</strong></div><div class="faq-a">', content_html)
    
    json_ld = create_json_ld(title, content[:200], keywords, current_url)
    
    social_html = f'''
    <div style="text-align: center; margin: 30px 0;">
        <div style="display: flex; justify-content: center; gap: 10px; flex-wrap: wrap;">
            <a href="https://twitter.com/intent/tweet?text={quote(clean_title[:60])}&url={quote(current_url)}" target="_blank" style="background:#1DA1F2; color:white; padding:8px 15px; border-radius:20px; text-decoration:none;">🐦 Twitter</a>
            <a href="https://www.facebook.com/sharer/sharer.php?u={quote(current_url)}" target="_blank" style="background:#4267B2; color:white; padding:8px 15px; border-radius:20px; text-decoration:none;">📘 Facebook</a>
            <a href="https://wa.me/?text={quote(clean_title[:50])}" target="_blank" style="background:#25D366; color:white; padding:8px 15px; border-radius:20px; text-decoration:none;">💬 WhatsApp</a>
        </div>
    </div>
    '''
    
    related_html = '''
    <div style="background: #f0f4f8; padding: 15px; border-radius: 10px; margin: 25px 0;">
        <h3 style="margin:0 0 10px 0;">📌 Related</h3>
        <ul style="margin:0; padding-left:20px;">
            <li><a href="https://newnews4public.blogspot.com/search/label/World">World News</a></li>
            <li><a href="https://newnews4public.blogspot.com/search/label/Space">Space News</a></li>
            <li><a href="https://newnews4public.blogspot.com/search/label/Analysis">Analysis</a></li>
        </ul>
    </div>
    '''
    
    html = f'''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{title[:150]} - Complete analysis. {keywords}">
<meta name="keywords" content="{keywords}, news, analysis">
<meta name="author" content="News Analysis Team">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{current_url}">
<meta property="og:title" content="{clean_title[:60]}">
<meta property="og:description" content="{title[:120]}">
<meta property="og:type" content="article">
<meta property="og:url" content="{current_url}">
<meta property="og:image" content="{images[0]['url'] if images else ''}">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{json.dumps(json_ld)}</script>
<title>{clean_title[:65]} | News Analysis</title>
<style>
    body {{ font-family: Georgia, serif; max-width: 780px; margin: 0 auto; padding: 20px; line-height: 1.8; font-size: 19px; }}
    h1 {{ font-size: 34px; }}
    h2 {{ font-size: 26px; margin-top: 35px; border-bottom: 2px solid #e0e0e0; padding-bottom: 6px; }}
    .meta {{ color: #666; font-size: 13px; margin-bottom: 25px; display: flex; justify-content: space-between; flex-wrap: wrap; }}
    .article-content p {{ margin-bottom: 22px; text-align: justify; text-indent: 1.5em; }}
    .article-content p:first-of-type {{ text-indent: 0; }}
    .article-content ul {{ margin: 15px 0 20px 30px; }}
    .article-content li {{ margin: 8px 0; }}
    .faq-q {{ font-weight: bold; margin: 25px 0 8px 0; }}
    .faq-a {{ margin-bottom: 15px; padding-left: 20px; border-left: 3px solid #e0e0e0; }}
    hr {{ margin: 40px 0; }}
    @media (max-width: 600px) {{ body {{ padding: 15px; font-size: 17px; }} h1 {{ font-size: 28px; }} .article-content p {{ text-indent: 1em; }} }}
</style>
</head>
<body>
<h1>{clean_title}</h1>
<div class="meta"><span>📅 {current_date}</span><span>📖 {reading_time} min read</span><span>📰 {source}</span><span>✍️ Analysis Team</span></div>
{images_html}
<div class="article-content">{content_html}</div>
{social_html}{related_html}
<hr><p style="text-align: center; font-size: 11px;">© {datetime.now().year} News Analysis | 🔍 {keywords}</p>
</body>
</html>'''
    
    post = service.posts().insert(blogId=BLOG_ID, body={'title': clean_title[:80], 'content': html}, isDraft=False).execute()
    print(f"   ✅ Published: {post.get('url')}")
    return post

def check_and_post():
    print(f"\n{'='*40}")
    print(f"📡 {datetime.now().strftime('%H:%M:%S')}")
    
    articles = fetch_news()
    if not articles:
        return
    
    processed = load_processed()
    for article in articles:
        story_id = article['title'][:60]
        if story_id in processed:
            continue
        
        print(f"\n📰 New: {article['title'][:55]}...")
        print(f"   Source: {article['source']}")
        
        print(f"   🖼️ Getting images...")
        images = get_images(article['title'])
        print(f"   Found {len(images)} images")
        
        print(f"   ✍️ Writing article...")
        content, keywords = write_article(article['title'], article.get('description', ''))
        print(f"   📝 {len(content.split())} words")
        
        service = google_login()
        if service:
            post_to_blogger(service, article['title'], content, images, article['source'], keywords)
            processed.add(story_id)
            save_processed(processed)
            print(f"   ✅ Published!")
        time.sleep(15)
    
    print(f"\n📊 Total: {len(processed)}")

def run():
    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║   📰 FINAL NEWS BOT - STABLE VERSION                        ║
    ║                                                              ║
    ║   ✓ Runs continuously until Ctrl+C                         ║
    ║   ✓ Checks news every 15 minutes                           ║
    ║   ✓ Auto-posts when news found                             ║
    ║   ✓ Press Ctrl+C once to stop (no traceback)               ║
    ╚══════════════════════════════════════════════════════════════╝
    """)
    
    print("✅ Bot is RUNNING")
    print("⏰ Checking for news every 15 minutes")
    print("📝 Will auto-post when news found")
    print("🛑 Press Ctrl+C once to stop\n")
    
    check_and_post()
    while running:
        print(f"\n💤 Next check in 15 minutes...")
        time.sleep(900)  # 15 minutes
        check_and_post()

if __name__ == "__main__":
    run()