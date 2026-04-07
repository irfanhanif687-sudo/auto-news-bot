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

# ========== RSS FEEDS ==========
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
            
            for entry in feed.entries[:4]:
                title = entry.get('title', '').strip()
                link = entry.get('link', '')
                description = entry.get('summary', '')[:400]
                description = re.sub(r'<[^>]+>', '', description)
                
                # Skip unwanted topics
                skip_words = ['beer', 'balloon', 'mortgage', 'recipe', 'cook', 'celebrity', 'gossip', 'student loan']
                if any(word in title.lower() for word in skip_words):
                    continue
                
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
    
    # Remove duplicates
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
            for i, photo in enumerate(photos[:2]):
                images.append({
                    'url': photo['src']['large'],
                    'alt': f"{title[:50]} - news photo",
                    'caption': title[:60],
                    'credit': photo.get('photographer', 'Pexels')
                })
    except:
        pass
    
    if not images:
        fallback = [
            'https://images.pexels.com/photos/6071605/pexels-photo-6071605.jpeg',
            'https://images.pexels.com/photos/1181467/pexels-photo-1181467.jpeg'
        ]
        for i, img_url in enumerate(fallback):
            images.append({
                'url': img_url,
                'alt': f"News image {i+1}",
                'caption': title[:50],
                'credit': 'Pexels'
            })
    
    return images[:2]

def write_human_article(title, description, source, retry_count=0):
    """Humanised article - real journalist style, no placeholders"""
    current_date = datetime.now().strftime("%B %d, %Y")
    
    prompt = f"""Write a complete news article. Make it sound like a real journalist wrote it.

TITLE: {title}
DATE: {current_date}
SOURCE: {source}
CONTEXT: {description[:400]}

IMPORTANT RULES:
- Write 600-1000 words
- NO placeholders like [LOCATION] or [DATE]
- Use specific details from the context
- Add realistic quotes from witnesses, officials, or experts
- Write short sentences (15-25 words)
- Start with a strong opening paragraph
- End naturally - no "in conclusion"
- Sound human, not like AI

STRUCTURE TO FOLLOW:
1. Opening: What happened, where, when
2. Details: What we know so far
3. Quotes: What people are saying
4. Context: Why this matters
5. What happens next

Write the complete article now:"""

    try:
        print(f"   ✍️ Writing article (attempt {retry_count + 1})...")
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            timeout=180
        )
        article = response.choices[0].message.content
        
        word_count = len(article.split())
        print(f"   📊 Word count: {word_count}")
        
        # Check for placeholders
        if ('[LOCATION]' in article or '[DATE]' in article or '[DAY]' in article or '[TIME]' in article) and retry_count < 2:
            print(f"   ⚠️ Found placeholders, retrying...")
            time.sleep(5)
            return write_human_article(title, description, source, retry_count + 1)
        
        if word_count < 400 and retry_count < 2:
            print(f"   ⚠️ Too short ({word_count} words), retrying...")
            time.sleep(5)
            return write_human_article(title, description, source, retry_count + 1)
        
        if word_count < 200:
            return get_human_fallback(title, description)
        
        return article
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        if retry_count < 2:
            print(f"   🔄 Retrying...")
            time.sleep(10)
            return write_human_article(title, description, source, retry_count + 1)
        return get_human_fallback(title, description)

def get_human_fallback(title, description):
    """Clean fallback - NO PLACEHOLDERS at all"""
    return f"""<p>Here's what we know so far about this developing story.</p>

<p>According to initial reports from officials and local authorities, this incident has occurred and is currently under active investigation.</p>

<p>"Our teams are on the scene and working to gather all the facts," a spokesperson told local media. "We will provide updates as more information becomes available to us."</p>

<p>Witnesses in the area described hearing loud noises and seeing emergency vehicles responding quickly. "It happened very suddenly," one person who was nearby said. "Everyone was shocked by what they saw unfold before them."</p>

<p>Local authorities have asked people to avoid the area while the investigation continues. Emergency services remain at the location.</p>

<p>This remains a developing situation. We will update this article when officials release additional details to the public.</p>

<p>The incident is being treated seriously by law enforcement. Further information is expected to be released in the coming hours as the investigation progresses.</p>"""

def post_to_blogger(service, title, content, images, source):
    current_date = datetime.now().strftime("%B %d, %Y")
    word_count = len(content.split())
    reading_time = max(4, round(word_count / 200))
    clean_title = title.replace('<', '&lt;').replace('>', '&gt;')
    
    # Create SEO-friendly slug
    slug = re.sub(r'[^a-z0-9]+', '-', clean_title.lower())[:60]
    current_url = f"https://newnews4public.blogspot.com/{datetime.now().year}/{datetime.now().month}/{slug}.html"
    
    # Images HTML
    images_html = ""
    for img in images:
        images_html += f'''
        <figure style="text-align: center; margin: 25px 0;">
            <img src="{img['url']}" alt="{img['alt'][:80]}" style="width:100%; max-width:750px; border-radius:12px;" loading="lazy">
            <figcaption style="font-size:12px; color:#666; margin-top:8px;">📷 {img['caption'][:70]} | Photo: {img['credit']}</figcaption>
        </figure>
        '''
    
    # Process content
    content_html = content.replace('\n\n', '</p><p>')
    content_html = f'<p>{content_html}</p>'
    content_html = content_html.replace('<p><h2>', '<h2>').replace('</h2></p>', '</h2>')
    content_html = content_html.replace('<p><h3>', '<h3>').replace('</h3></p>', '</h3>')
    
    # Categories
    categories = ['World News']
    if any(word in title.lower() for word in ['iran', 'israel', 'trump', 'us', 'china', 'russia', 'ukraine', 'gaza', 'lebanon', 'turkey', 'france', 'africa']):
        categories.append('Politics')
    if any(word in title.lower() for word in ['oil', 'economy', 'market', 'price', 'inflation']):
        categories.append('Business')
    
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
        body {{ font-family: 'Georgia', 'Times New Roman', serif; max-width: 800px; margin: 0 auto; padding: 20px; line-height: 1.7; font-size: 18px; color: #1a1a1a; background: #fff; }}
        h1 {{ font-size: 36px; line-height: 1.3; margin-bottom: 15px; color: #000; }}
        h2 {{ font-size: 26px; margin: 40px 0 20px 0; border-bottom: 2px solid #1a73e8; padding-bottom: 8px; color: #000; }}
        .meta {{ color: #666; font-size: 13px; margin-bottom: 25px; padding-bottom: 15px; border-bottom: 1px solid #e0e0e0; display: flex; justify-content: space-between; flex-wrap: wrap; }}
        .article-content p {{ margin-bottom: 22px; text-align: justify; line-height: 1.7; }}
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

<div class="article-content">
    {content_html}
</div>

<hr>

<div style="text-align: center; font-size: 12px; color: #999;">
    <p>© {datetime.now().year} News Analysis | In-Depth Coverage</p>
</div>

</body>
</html>'''
    
    post = service.posts().insert(
        blogId=BLOG_ID,
        body={'title': clean_title[:70], 'content': html, 'labels': categories},
        isDraft=False
    ).execute()
    print(f"   ✅ Published: {post.get('url')}")
    return post

def check_and_post():
    print(f"\n{'='*50}")
    print(f"📡 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")
    
    articles = fetch_news()
    if not articles:
        print("   📭 No new stories")
        return
    
    processed = load_processed()
    
    for article in articles:
        story_id = article['title'][:80]
        if story_id in processed:
            print(f"   ⏭️ Already posted: {article['title'][:50]}...")
            continue
        
        print(f"\n📰 {article['title'][:70]}...")
        print(f"   Source: {article['source']}")
        
        print(f"   🖼️ Getting images...")
        images = get_images(article['title'])
        
        print(f"   ✍️ Writing humanised article...")
        content = write_human_article(
            article['title'], 
            article.get('description', ''), 
            article['source']
        )
        
        word_count = len(content.split())
        print(f"   📝 Final word count: {word_count}")
        
        # Final check for placeholders
        if '[LOCATION]' in content or '[DATE]' in content or '[DAY]' in content:
            print(f"   ⚠️ WARNING: Placeholders found! Using fallback instead.")
            content = get_human_fallback(article['title'], article.get('description', ''))
        
        service = google_login()
        if service:
            post_to_blogger(service, article['title'], content, images, article['source'])
            processed.add(story_id)
            save_processed(processed)
            print(f"   ✅ Published successfully!")
        
        break

def run():
    print("""
    ╔══════════════════════════════════════════════════════════════════════╗
    ║         📰 FINAL HUMANISED NEWS BOT - COMPLETE VERSION              ║
    ║                                                                      ║
    ║   ✓ Humanised articles (real journalist style)                      ║
    ║   ✓ NO placeholders like [LOCATION]                                 ║
    ║   ✓ Clean fallback with no brackets                                 ║
    ║   ✓ Text justified (newspaper style)                                ║
    ║   ✓ Retry logic for short articles                                  ║
    ║   ✓ Runs every 10 minutes                                           ║
    ╚══════════════════════════════════════════════════════════════════════╝
    """)
    
    print("✅ Bot is RUNNING on GitHub Actions")
    print("⏰ Runs every 10 minutes")
    print("📝 Writing humanised articles (no placeholders)\n")
    
    check_and_post()

if __name__ == "__main__":
    run()
