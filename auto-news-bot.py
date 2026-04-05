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

# ========== MORE RSS FEEDS ==========
RSS_FEEDS = [
    'http://feeds.bbci.co.uk/news/world/rss.xml',
    'http://feeds.bbci.co.uk/news/technology/rss.xml',
    'http://feeds.bbci.co.uk/news/business/rss.xml',
    'https://www.aljazeera.com/xml/rss/all.xml',
    'https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml',
    'https://feeds.npr.org/1001/rss.xml',
    'https://rss.cnn.com/rss/edition.rss',
    'https://www.theguardian.com/world/rss',
]

def fetch_all_news():
    """Fetch ALL new stories from ALL RSS feeds"""
    articles = []
    processed = load_processed()
    print(f"   📡 Checking {len(RSS_FEEDS)} RSS feeds...")
    
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            print(f"      📻 {feed.feed.get('title', 'Unknown')[:30]} - {len(feed.entries)} stories")
            
            for entry in feed.entries[:5]:  # 5 stories per feed
                title = entry.get('title', '').strip()
                link = entry.get('link', '')
                description = entry.get('summary', '')[:300]
                description = re.sub(r'<[^>]+>', '', description)
                
                if title and link and len(title) > 20:
                    story_id = title[:80]  # Longer ID for uniqueness
                    if story_id not in processed:
                        source = feed.feed.get('title', 'News').split(' - ')[0][:30]
                        articles.append({
                            'title': title,
                            'url': link,
                            'description': description,
                            'source': source,
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
    return unique  # Return ALL new stories

def generate_seo_keywords(title, description, source):
    """Generate SEO-optimized keywords"""
    prompt = f"""Generate 15 SEO keywords for this news article:

Title: {title}
Description: {description[:200]}
Source: {source}

Rules:
- Mix of short-tail and long-tail keywords
- Include location names if mentioned
- Include trending terms
- Format as comma-separated list only, no explanation

Example: "US Iran conflict, Middle East crisis, Tehran Washington tensions, Gulf security, oil prices spike, diplomatic relations, military standoff, international news, breaking news today, world politics, US foreign policy, Iran nuclear deal, Strait of Hormuz, global economy, latest updates"

Generate now:"""
    
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            timeout=30
        )
        keywords = response.choices[0].message.content.strip()
        return keywords[:500]
    except:
        # Fallback keywords
        words = re.findall(r'\b[A-Za-z]{4,}\b', title)
        return ', '.join(words[:10]) + ', news, breaking news, latest updates, world news'

def generate_seo_description(title, description):
    """Generate SEO meta description"""
    prompt = f"""Write a compelling SEO meta description (150-160 characters) for:
Title: {title}
Context: {description}

Rules:
- Include main keyword
- End with call to action
- Exactly 150-160 characters
- No quotes in response

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
        return f"{title[:140]}... Read full analysis on our blog."

def get_images(title):
    """Get images with SEO alt text"""
    images = []
    keywords = ' '.join(title.split()[:5])
    
    search_terms = [keywords, f"{keywords} news", f"{keywords} latest"]
    
    for i, term in enumerate(search_terms[:3]):
        try:
            url = f"https://api.pexels.com/v1/search?query={quote(term)}&per_page=5&orientation=landscape"
            headers = {"Authorization": PEXELS_API_KEY}
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                photos = data.get('photos', [])
                if photos:
                    photo = photos[0]
                    images.append({
                        'url': photo['src']['large'],
                        'alt': f"{title[:60]} - news photo",
                        'caption': title[:80],
                        'credit': photo.get('photographer', 'Pexels'),
                        'photographer_url': photo.get('photographer_url', '')
                    })
                    continue
        except:
            pass
        
        fallback = [
            ('https://images.pexels.com/photos/6071605/pexels-photo-6071605.jpeg', 'Global news view', 'World affairs'),
            ('https://images.pexels.com/photos/1181467/pexels-photo-1181467.jpeg', 'Technology news', 'Latest tech'),
            ('https://images.pexels.com/photos/210607/pexels-photo-210607.jpeg', 'Breaking news', 'Current events')
        ]
        images.append({
            'url': fallback[i][0],
            'alt': fallback[i][1],
            'caption': fallback[i][2],
            'credit': 'Pexels'
        })
    
    return images

def write_seo_article(title, description, source):
    """Write SEO-optimized article"""
    current_date = datetime.now().strftime("%B %d, %Y")
    keywords = generate_seo_keywords(title, description, source)
    meta_desc = generate_seo_description(title, description)
    
    prompt = f"""Write a comprehensive, SEO-optimized news article.

TODAY'S DATE: {current_date}
TITLE: {title}
SOURCE: {source}
CONTEXT: {description[:300]}
TARGET KEYWORDS: {keywords[:200]}

STRUCTURE:

## Introduction
(2 paragraphs, include main keyword in first paragraph)

## Key Takeaways (Bullet points)
- 5-7 key points with bold keywords

## Background & Context
(2-3 paragraphs with LSI keywords)

## Detailed Analysis
(3-4 paragraphs with subheadings)

## Expert Opinions & Reactions
(2 paragraphs)

## Impact & Implications
(2 paragraphs with long-tail keywords)

## Frequently Asked Questions

**Q1: [Keyword-rich question]**
Answer with 2-3 sentences

**Q2: [Secondary keyword question]**
Answer with 2-3 sentences

**Q3: [Tertiary keyword question]**
Answer with 2-3 sentences

## Future Outlook
(2 paragraphs)

## Conclusion
(2 paragraphs with call to action)

SEO RULES:
- Use primary keyword in first 100 words
- Use secondary keywords naturally
- Write 1200-1500 words
- Each paragraph: 2-3 sentences
- Include numbers, statistics, dates
- Bold important phrases with <strong>
- Use bullet points for lists
- Add internal links naturally

Write the complete article now:"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            timeout=120
        )
        article = response.choices[0].message.content
        article = re.sub(r'^#.*$', '', article, flags=re.MULTILINE)
        return article, keywords, meta_desc
    except Exception as e:
        print(f"   AI Error: {e}")
        return get_fallback_article(title, description), keywords, meta_desc

def get_fallback_article(title, description):
    return f"""<h2>Introduction</h2>
<p>{description if description else title}</p>

<h2>Key Takeaways</h2>
<ul><li><strong>{title[:100]}</strong></li><li>Major development in this ongoing story</li><li>Global implications being analyzed</li></ul>

<h2>Analysis</h2>
<p>This breaking news story continues to develop. Our team is monitoring the situation closely.</p>

<h2>Conclusion</h2>
<p>Stay tuned to News Analysis for the latest updates on this developing story.</p>"""

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
        "author": {
            "@type": "Organization",
            "name": "News Analysis Team",
            "url": "https://newnews4public.blogspot.com"
        },
        "publisher": {
            "@type": "Organization",
            "name": "News Analysis",
            "logo": {
                "@type": "ImageObject",
                "url": "https://newnews4public.blogspot.com/favicon.ico"
            }
        },
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id": current_url
        },
        "image": images[0]['url'] if images else "",
        "articleSection": "World News",
        "wordCount": len(description.split()),
        "isAccessibleForFree": True
    }

def post_to_blogger(service, title, content, images, source, keywords, meta_desc):
    """Post with full SEO optimization"""
    current_date = datetime.now().strftime("%B %d, %Y")
    word_count = len(content.split())
    reading_time = max(5, round(word_count / 200))
    clean_title = title.replace('<', '&lt;').replace('>', '&gt;')
    
    # Create SEO-friendly slug
    slug = re.sub(r'[^a-z0-9]+', '-', clean_title.lower())[:60]
    current_url = f"https://newnews4public.blogspot.com/{datetime.now().year}/{datetime.now().month}/{slug}.html"
    date_published = datetime.now().isoformat()
    
    # Images HTML with SEO
    images_html = ""
    for i, img in enumerate(images[:2]):
        images_html += f'''
        <figure style="text-align: center; margin: 25px 0;">
            <img src="{img['url']}" alt="{img['alt'][:80]}" style="width:100%; max-width:750px; border-radius:12px; box-shadow:0 4px 12px rgba(0,0,0,0.1);" loading="lazy">
            <figcaption style="font-size:12px; color:#666; margin-top:8px;">📷 {img['caption'][:70]} | Photo: {img['credit']}</figcaption>
        </figure>
        '''
    
    # Process content
    content_html = content.replace('\n\n', '</p><p>')
    content_html = f'<p>{content_html}</p>'
    content_html = content_html.replace('<p><h2>', '<h2>').replace('</h2></p>', '</h2>')
    content_html = content_html.replace('<p><ul>', '<ul>').replace('</ul></p>', '</ul>')
    content_html = content_html.replace('<p><li>', '<li>').replace('</li></p>', '</li>')
    content_html = re.sub(r'\*\*Q(\d+): (.*?)\*\*\s*\n', r'<div class="faq-q"><strong>❓ Q\1: \2</strong></div><div class="faq-a">', content_html)
    content_html = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', content_html)
    
    # SEO Schema
    schema = create_seo_schema(title, meta_desc, keywords, current_url, images, date_published)
    
    # Categories based on keywords
    categories = []
    if any(word in title.lower() for word in ['iran', 'israel', 'gaza', 'middle east', 'trump', 'us', 'china', 'russia', 'ukraine']):
        categories.append('World Politics')
    if any(word in title.lower() for word in ['economy', 'market', 'oil', 'trade', 'stock', 'bank']):
        categories.append('Business & Economy')
    if any(word in title.lower() for word in ['tech', 'ai', 'space', 'nasa', 'robot', 'internet']):
        categories.append('Technology')
    if not categories:
        categories = ['World News', 'Breaking News']
    
    categories_html = ''.join([f'<a href="/search/label/{quote(cat)}" style="display:inline-block; background:#f0f4f8; padding:4px 12px; border-radius:20px; margin:0 5px 5px 0; text-decoration:none; color:#1a73e8; font-size:13px;">#{cat}</a>' for cat in categories])
    
    # Share buttons with SEO tracking
    social_html = f'''
    <div style="text-align: center; margin: 35px 0; padding: 20px; background: #f8f9fa; border-radius: 16px;">
        <h3 style="margin:0 0 15px 0;">📢 Share This News</h3>
        <div style="display: flex; justify-content: center; gap: 12px; flex-wrap: wrap;">
            <a href="https://twitter.com/intent/tweet?text={quote(clean_title[:70])}&url={quote(current_url)}&hashtags={quote(','.join(categories[:3]))}" target="_blank" style="background:#1DA1F2; color:white; padding:10px 20px; border-radius:30px; text-decoration:none; display:inline-flex; align-items:center; gap:8px;">🐦 Twitter</a>
            <a href="https://www.facebook.com/sharer/sharer.php?u={quote(current_url)}" target="_blank" style="background:#4267B2; color:white; padding:10px 20px; border-radius:30px; text-decoration:none; display:inline-flex; align-items:center; gap:8px;">📘 Facebook</a>
            <a href="https://www.linkedin.com/shareArticle?mini=true&url={quote(current_url)}&title={quote(clean_title[:60])}" target="_blank" style="background:#0077B5; color:white; padding:10px 20px; border-radius:30px; text-decoration:none; display:inline-flex; align-items:center; gap:8px;">🔗 LinkedIn</a>
            <a href="https://wa.me/?text={quote(clean_title[:50] + ' ' + current_url)}" target="_blank" style="background:#25D366; color:white; padding:10px 20px; border-radius:30px; text-decoration:none; display:inline-flex; align-items:center; gap:8px;">💬 WhatsApp</a>
        </div>
    </div>
    '''
    
    # Related posts section
    related_html = f'''
    <div style="background: linear-gradient(135deg, #f5f7fa 0%, #e8ecf1 100%); padding: 20px; border-radius: 16px; margin: 30px 0;">
        <h3 style="margin:0 0 15px 0;">📌 Related News</h3>
        <div style="display: flex; gap: 10px; flex-wrap: wrap;">
            {categories_html}
        </div>
        <p style="margin:15px 0 0 0; font-size:14px;">🔍 <strong>Keywords:</strong> {keywords[:200]}</p>
    </div>
    '''
    
    # Newsletter signup
    newsletter_html = '''
    <div style="background: #1a73e8; color: white; padding: 25px; border-radius: 16px; text-align: center; margin: 30px 0;">
        <h3 style="margin:0 0 10px 0;">📧 Never Miss a News Update</h3>
        <p style="margin:0 0 15px 0;">Subscribe to get the latest analysis directly in your inbox.</p>
        <div style="display: flex; gap: 10px; justify-content: center; flex-wrap: wrap;">
            <input type="email" placeholder="Your email address" style="padding: 10px 15px; border-radius: 30px; border: none; width: 250px;">
            <button style="background: white; color: #1a73e8; padding: 10px 25px; border-radius: 30px; border: none; font-weight: bold; cursor: pointer;">Subscribe →</button>
        </div>
    </div>
    '''
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{clean_title[:70]} | In-Depth News Analysis</title>
    <meta name="description" content="{meta_desc}">
    <meta name="keywords" content="{keywords[:200]}">
    <meta name="author" content="News Analysis Team">
    <meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large">
    <link rel="canonical" href="{current_url}">
    
    <!-- Open Graph / Social Media -->
    <meta property="og:title" content="{clean_title[:65]}">
    <meta property="og:description" content="{meta_desc}">
    <meta property="og:type" content="article">
    <meta property="og:url" content="{current_url}">
    <meta property="og:image" content="{images[0]['url'] if images else ''}">
    <meta property="og:site_name" content="News Analysis">
    <meta property="article:published_time" content="{date_published}">
    <meta property="article:tag" content="{', '.join(categories)}">
    
    <!-- Twitter Card -->
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{clean_title[:65]}">
    <meta name="twitter:description" content="{meta_desc}">
    <meta name="twitter:image" content="{images[0]['url'] if images else ''}">
    
    <!-- Schema.org markup -->
    <script type="application/ld+json">{json.dumps(schema)}</script>
    
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Georgia', 'Times New Roman', serif; max-width: 850px; margin: 0 auto; padding: 20px; line-height: 1.8; font-size: 19px; color: #1a1a1a; background: #fff; }}
        h1 {{ font-size: 38px; line-height: 1.3; margin-bottom: 15px; color: #000; }}
        h2 {{ font-size: 28px; margin: 40px 0 20px 0; border-bottom: 3px solid #1a73e8; padding-bottom: 10px; color: #000; }}
        h3 {{ font-size: 22px; margin: 30px 0 15px 0; color: #1a1a1a; }}
        .meta {{ color: #666; font-size: 14px; margin-bottom: 25px; padding-bottom: 15px; border-bottom: 1px solid #e0e0e0; display: flex; justify-content: space-between; flex-wrap: wrap; }}
        .article-content p {{ margin-bottom: 25px; text-align: justify; }}
        .article-content ul, .article-content ol {{ margin: 20px 0 25px 40px; }}
        .article-content li {{ margin: 8px 0; }}
        .faq-q {{ font-weight: bold; margin: 30px 0 10px 0; font-size: 18px; color: #1a73e8; }}
        .faq-a {{ margin-bottom: 20px; padding-left: 20px; border-left: 4px solid #1a73e8; }}
        hr {{ margin: 40px 0; border: none; height: 1px; background: linear-gradient(to right, transparent, #ccc, transparent); }}
        @media (max-width: 600px) {{ body {{ padding: 15px; font-size: 17px; }} h1 {{ font-size: 28px; }} h2 {{ font-size: 22px; }} }}
    </style>
</head>
<body>

<h1>{clean_title}</h1>

<div class="meta">
    <span>📅 {current_date}</span>
    <span>📖 {reading_time} min read</span>
    <span>📰 {source}</span>
    <span>✍️ Analysis Team</span>
</div>

{images_html}

<div class="article-content">
    {content_html}
</div>

{social_html}
{related_html}
{newsletter_html}

<hr>

<div style="text-align: center; font-size: 12px; color: #999;">
    <p>© {datetime.now().year} News Analysis | All Rights Reserved</p>
    <p>🔍 {keywords[:150]} | #{' #'.join(categories)}</p>
    <p><a href="https://newnews4public.blogspot.com/" style="color: #1a73e8;">Home</a> | <a href="/p/privacy-policy.html" style="color: #1a73e8;">Privacy Policy</a> | <a href="/p/contact.html" style="color: #1a73e8;">Contact</a></p>
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
    
    # Get ALL new articles
    articles = fetch_all_news()
    if not articles:
        print("   📭 No new stories found")
        return
    
    processed = load_processed()
    published_count = 0
    
    # Post ALL new articles (one by one)
    for article in articles:
        story_id = article['title'][:80]
        if story_id in processed:
            print(f"   ⏭️ Skipping (already posted): {article['title'][:50]}...")
            continue
        
        print(f"\n{'─'*40}")
        print(f"📰 NEW: {article['title'][:60]}...")
        print(f"   Source: {article['source']}")
        print(f"   Published: {article.get('published', 'Unknown')}")
        
        print(f"   🖼️ Getting images...")
        images = get_images(article['title'])
        print(f"   ✅ {len(images)} images ready")
        
        print(f"   ✍️ Writing SEO article...")
        content, keywords, meta_desc = write_seo_article(
            article['title'], 
            article.get('description', ''), 
            article['source']
        )
        print(f"   📝 {len(content.split())} words | SEO keywords generated")
        
        print(f"   🔑 Meta description: {meta_desc[:80]}...")
        
        service = google_login()
        if service:
            post_to_blogger(service, article['title'], content, images, article['source'], keywords, meta_desc)
            processed.add(story_id)
            save_processed(processed)
            published_count += 1
            print(f"   ✅ Published! (Post #{published_count} this run)")
        
        # Small delay between posts to avoid rate limits
        time.sleep(10)
    
    print(f"\n{'='*50}")
    print(f"📊 SUMMARY: {published_count} new articles published this run")
    print(f"📊 Total published so far: {len(processed)}")
    print(f"{'='*50}")

def run():
    print("""
    ╔══════════════════════════════════════════════════════════════════════╗
    ║         📰 PROFESSIONAL NEWS BOT - SEO OPTIMIZED VERSION            ║
    ║                                                                      ║
    ║   ✓ ALL news from 8+ RSS feeds                                      ║
    ║   ✓ SEO-optimized keywords and meta descriptions                    ║
    ║   ✓ 1200-1500 word articles                                        ║
    ║   ✓ Full Schema.org markup for search engines                       ║
    ║   ✓ Social sharing buttons with hashtags                            ║
    ║   ✓ No duplicates - processed_news.json tracking                    ║
    ║   ✓ Runs every 30 minutes on GitHub Actions                         ║
    ╚══════════════════════════════════════════════════════════════════════╝
    """)
    
    print("✅ Bot is RUNNING on GitHub Actions")
    print("⏰ Checking ALL RSS feeds (8+ sources)")
    print("📝 Will post ALL new articles found")
    print("🔍 SEO optimization enabled\n")
    
    check_and_post()

if __name__ == "__main__":
    run()
