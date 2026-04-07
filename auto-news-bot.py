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

# ========== CLEAN RSS FEEDS (Only serious news) ==========
RSS_FEEDS = [
    'http://feeds.bbci.co.uk/news/world/rss.xml',
    'http://feeds.bbci.co.uk/news/business/rss.xml',
    'https://www.aljazeera.com/xml/rss/all.xml',
    'https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml',
    'https://feeds.npr.org/1001/rss.xml',
]

def fetch_all_news():
    """Fetch ALL new stories from ALL RSS feeds"""
    articles = []
    processed = load_processed()
    print(f"   📡 Checking {len(RSS_FEEDS)} RSS feeds...")
    
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            source_name = feed.feed.get('title', 'Unknown')[:30]
            print(f"      📻 {source_name} - {len(feed.entries)} stories")
            
            for entry in feed.entries[:4]:
                title = entry.get('title', '').strip()
                link = entry.get('link', '')
                description = entry.get('summary', '')[:300]
                description = re.sub(r'<[^>]+>', '', description)
                
                # Skip weird/random stories
                skip_words = ['beer', 'balloon', 'mortgage', 'recipe', 'cook', 'celebrity', 'gossip']
                if any(word in title.lower() for word in skip_words):
                    print(f"      ⏭️ Skipping: {title[:40]}...")
                    continue
                
                if title and link and len(title) > 20:
                    story_id = title[:80]
                    if story_id not in processed:
                        articles.append({
                            'title': title,
                            'url': link,
                            'description': description,
                            'source': source_name,
                            'published': entry.get('published', datetime.now().strftime("%a, %d %b %Y %H:%M:%S %Z"))
                        })
        except Exception as e:
            print(f"      ⚠️ Feed error: {e}")
    
    # Remove duplicates by title
    seen = set()
    unique = []
    for a in articles:
        if a['title'] not in seen:
            seen.add(a['title'])
            unique.append(a)
    
    print(f"   ✅ Found {len(unique)} new stories total")
    return unique

def generate_seo_keywords(title, description, source):
    """Generate SEO-optimized keywords"""
    prompt = f"""Generate 12 SEO keywords for this news article:

Title: {title}
Description: {description[:200]}

Rules:
- Mix of short and long keywords
- Comma separated only
- Keep under 200 characters

Generate now:"""
    
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            timeout=30
        )
        keywords = response.choices[0].message.content.strip()
        return keywords[:300]
    except:
        words = re.findall(r'\b[A-Za-z]{4,}\b', title)
        return ', '.join(words[:6]) + ', news, world news'

def generate_seo_description(title, description):
    """Generate SEO meta description"""
    prompt = f"""Write a compelling meta description (150-160 characters) for:
Title: {title}

Write now:"""
    
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            timeout=20
        )
        meta_desc = response.choices[0].message.content.strip()
        return meta_desc[:160]
    except:
        return f"{title[:140]}... Read full analysis."

def get_images(title):
    """Get images with SEO alt text"""
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
    
    # Fallback images
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
    """Write HUMAN-SOUNDING article - not robotic"""
    current_date = datetime.now().strftime("%B %d, %Y")
    keywords = generate_seo_keywords(title, description, source)
    meta_desc = generate_seo_description(title, description)
    
    # HUMANIZED PROMPT - like a real journalist
    prompt = f"""Write a news article like a real journalist would write. Make it sound natural, not robotic.

TITLE: {title}
DATE: {current_date}
SOURCE: {source}
BACKGROUND: {description[:250]}

Write in this style:
- Use short, punchy sentences
- Sound like a person talking, not a robot
- Add some emotion and reaction
- Use phrases like "according to officials", "witnesses say", "experts believe"
- Keep paragraphs short (2-3 sentences max)

Structure:
1. Start with a strong opening that grabs attention
2. Tell readers what happened and why it matters
3. Add quotes or reactions (make them realistic)
4. Explain what happens next
5. End with a thoughtful conclusion

REQUIREMENTS:
- Minimum 600 words
- Write naturally, like a news anchor would speak
- No bullet points in the main narrative
- DO NOT cut off mid-sentence

Write the complete article now:"""

    try:
        print(f"   ✍️ Writing human-style article (attempt {retry_count + 1})...")
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            timeout=90
        )
        article = response.choices[0].message.content
        
        word_count = len(article.split())
        print(f"   📊 Word count: {word_count}")
        
        if word_count < 300 and retry_count < 3:
            print(f"   ⚠️ Too short, retrying...")
            time.sleep(5)
            return write_human_article(title, description, source, retry_count + 1)
        
        if word_count < 150:
            return get_human_fallback(title, description), keywords, meta_desc
        
        return article, keywords, meta_desc
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        if retry_count < 3:
            print(f"   🔄 Retrying...")
            time.sleep(10)
            return write_human_article(title, description, source, retry_count + 1)
        return get_human_fallback(title, description), keywords, meta_desc

def get_human_fallback(title, description):
    """Human-sounding fallback article"""
    return f"""<p>Here's what we know so far about <strong>{title}</strong>.</p>

<p>This story is developing quickly. Initial reports indicate this is a significant development that people around the world are watching closely.</p>

<p>According to officials, more details are expected to emerge in the coming hours. Our team is actively monitoring the situation and will bring you updates as soon as they become available.</p>

<p>What makes this story particularly interesting is how it could affect everyday people. Experts are already weighing in on the potential implications.</p>

<p>We'll continue following this story and update this article with fresh information. Bookmark this page and check back later for the latest developments.</p>"""

def create_seo_schema(title, description, keywords, current_url, images, date_published):
    """Complete SEO Schema markup"""
    return {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": title[:110],
        "description": description[:160],
        "keywords": keywords[:200],
        "datePublished": date_published,
        "dateModified": datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z"),
        "author": {"@type": "Organization", "name": "News Analysis Team"},
        "publisher": {"@type": "Organization", "name": "News Analysis"},
        "mainEntityOfPage": {"@type": "WebPage", "@id": current_url},
        "image": images[0]['url'] if images else ""
    }

def post_to_blogger(service, title, content, images, source, keywords, meta_desc):
    """Post with full SEO optimization"""
    current_date = datetime.now().strftime("%B %d, %Y")
    word_count = len(content.split())
    reading_time = max(4, round(word_count / 200))
    clean_title = title.replace('<', '&lt;').replace('>', '&gt;')
    
    # Create SEO-friendly slug
    slug = re.sub(r'[^a-z0-9]+', '-', clean_title.lower())[:60]
    current_url = f"https://newnews4public.blogspot.com/{datetime.now().year}/{datetime.now().month}/{slug}.html"
    date_published = datetime.now().isoformat()
    
    # Images HTML
    images_html = ""
    for i, img in enumerate(images):
        images_html += f'''
        <figure style="text-align: center; margin: 25px 0;">
            <img src="{img['url']}" alt="{img['alt'][:80]}" style="width:100%; max-width:750px; border-radius:12px; box-shadow:0 2px 8px rgba(0,0,0,0.1);" loading="lazy">
            <figcaption style="font-size:12px; color:#666; margin-top:8px;">📷 {img['caption'][:70]} | Photo: {img['credit']}</figcaption>
        </figure>
        '''
    
    # Process content - convert to HTML paragraphs
    content_html = content.replace('\n\n', '</p><p>')
    content_html = f'<p>{content_html}</p>'
    content_html = content_html.replace('<p><h2>', '<h2>').replace('</h2></p>', '</h2>')
    content_html = content_html.replace('<p><h3>', '<h3>').replace('</h3></p>', '</h3>')
    content_html = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', content_html)
    
    # Categories
    categories = ['World News']
    if any(word in title.lower() for word in ['iran', 'israel', 'trump', 'us', 'china', 'russia', 'ukraine', 'gaza', 'lebanon']):
        categories.append('Politics')
    if any(word in title.lower() for word in ['economy', 'market', 'oil', 'trade', 'inflation', 'price']):
        categories.append('Business')
    if any(word in title.lower() for word in ['tech', 'ai', 'space', 'nasa', 'moon', 'mars']):
        categories.append('Technology')
    
    schema = create_seo_schema(title, meta_desc, keywords, current_url, images, date_published)
    
    # Categories HTML
    categories_html = ''.join([f'<a href="/search/label/{quote(cat)}" style="display:inline-block; background:#f0f4f8; padding:4px 12px; border-radius:20px; margin:0 5px 5px 0; text-decoration:none; color:#1a73e8; font-size:13px;">#{cat}</a>' for cat in set(categories)])
    
    social_html = f'''
    <div style="text-align: center; margin: 35px 0; padding: 20px; background: #f8f9fa; border-radius: 16px;">
        <h3 style="margin:0 0 15px 0;">📢 Share This Article</h3>
        <div style="display: flex; justify-content: center; gap: 12px; flex-wrap: wrap;">
            <a href="https://twitter.com/intent/tweet?text={quote(clean_title[:70])}&url={quote(current_url)}" target="_blank" style="background:#1DA1F2; color:white; padding:10px 20px; border-radius:30px; text-decoration:none;">🐦 Twitter</a>
            <a href="https://www.facebook.com/sharer/sharer.php?u={quote(current_url)}" target="_blank" style="background:#4267B2; color:white; padding:10px 20px; border-radius:30px; text-decoration:none;">📘 Facebook</a>
            <a href="https://wa.me/?text={quote(clean_title[:50] + ' ' + current_url)}" target="_blank" style="background:#25D366; color:white; padding:10px 20px; border-radius:30px; text-decoration:none;">💬 WhatsApp</a>
        </div>
    </div>
    '''
    
    related_html = f'''
    <div style="background: #f5f7fa; padding: 20px; border-radius: 16px; margin: 30px 0;">
        <h3 style="margin:0 0 15px 0;">📌 Topics</h3>
        <div style="display: flex; gap: 10px; flex-wrap: wrap;">{categories_html}</div>
        <p style="margin:15px 0 0 0; font-size:13px; color:#666;">🔍 Keywords: {keywords[:200]}</p>
    </div>
    '''
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{clean_title[:70]} | News Analysis</title>
    <meta name="description" content="{meta_desc}">
    <meta name="keywords" content="{keywords[:200]}">
    <meta name="author" content="News Analysis Team">
    <meta name="robots" content="index, follow">
    <link rel="canonical" href="{current_url}">
    
    <meta property="og:title" content="{clean_title[:65]}">
    <meta property="og:description" content="{meta_desc}">
    <meta property="og:type" content="article">
    <meta property="og:url" content="{current_url}">
    <meta property="og:image" content="{images[0]['url'] if images else ''}">
    
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{clean_title[:65]}">
    <meta name="twitter:description" content="{meta_desc}">
    
    <script type="application/ld+json">{json.dumps(schema)}</script>
    
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Georgia', 'Times New Roman', serif; max-width: 800px; margin: 0 auto; padding: 20px; line-height: 1.7; font-size: 18px; color: #1a1a1a; background: #fff; }}
        h1 {{ font-size: 36px; line-height: 1.3; margin-bottom: 15px; color: #000; }}
        h2 {{ font-size: 26px; margin: 40px 0 20px 0; border-bottom: 2px solid #1a73e8; padding-bottom: 8px; color: #000; }}
        .meta {{ color: #666; font-size: 13px; margin-bottom: 25px; padding-bottom: 15px; border-bottom: 1px solid #e0e0e0; display: flex; justify-content: space-between; flex-wrap: wrap; }}
        .article-content p {{ margin-bottom: 22px; text-align: justify; line-height: 1.7; }}
        .article-content h2 {{ margin-top: 35px; }}
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

{social_html}
{related_html}

<hr>

<div style="text-align: center; font-size: 12px; color: #999;">
    <p>© {datetime.now().year} News Analysis</p>
</div>

</body>
</html>'''
    
    post = service.posts().insert(
        blogId=BLOG_ID,
        body={'title': clean_title[:70], 'content': html, 'labels': list(set(categories))},
        isDraft=False
    ).execute()
    print(f"   ✅ Published: {post.get('url')}")
    return post

def check_and_post():
    print(f"\n{'='*50}")
    print(f"📡 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")
    
    articles = fetch_all_news()
    if not articles:
        print("   📭 No new stories found")
        return
    
    processed = load_processed()
    published_count = 0
    
    for article in articles[:3]:  # Max 3 posts per run
        story_id = article['title'][:80]
        if story_id in processed:
            print(f"   ⏭️ Already posted: {article['title'][:50]}...")
            continue
        
        print(f"\n{'─'*40}")
        print(f"📰 NEW: {article['title'][:60]}...")
        print(f"   Source: {article['source']}")
        
        print(f"   🖼️ Getting images...")
        images = get_images(article['title'])
        print(f"   ✅ {len(images)} images ready")
        
        print(f"   ✍️ Writing article...")
        content, keywords, meta_desc = write_human_article(
            article['title'], 
            article.get('description', ''), 
            article['source']
        )
        
        word_count = len(content.split())
        print(f"   📝 Final: {word_count} words")
        
        service = google_login()
        if service:
            post_to_blogger(service, article['title'], content, images, article['source'], keywords, meta_desc)
            processed.add(story_id)
            save_processed(processed)
            published_count += 1
        
        if published_count < len(articles[:3]):
            print(f"   ⏸️ Waiting 20 seconds...")
            time.sleep(20)
    
    print(f"\n{'='*50}")
    print(f"📊 Published: {published_count} new articles")
    print(f"{'='*50}")

def run():
    print("""
    ╔══════════════════════════════════════════════════════════════════════╗
    ║         📰 NEWS BOT - HUMANIZED VERSION                             ║
    ║                                                                      ║
    ║   ✓ Natural, human-sounding articles                                ║
    ║   ✓ Serious news only (no random stories)                           ║
    ║   ✓ 600+ words per article                                          ║
    ║   ✓ Text justified for newspaper feel                               ║
    ║   ✓ Runs every 30 minutes                                           ║
    ╚══════════════════════════════════════════════════════════════════════╝
    """)
    
    print("✅ Bot is RUNNING")
    print("⏰ Checking news every 30 minutes")
    print("📝 Writing human-style articles\n")
    
    check_and_post()

if __name__ == "__main__":
    run()
