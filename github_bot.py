import requests
import feedparser
import json
import re
import os
from datetime import datetime
from groq import Groq
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
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
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('blogger', 'v3', credentials=creds)
    return None

def fetch_news():
    articles = []
    processed = load_processed()
    print("📡 Checking RSS feeds...")
    
    RSS_FEEDS = [
        'http://feeds.bbci.co.uk/news/world/rss.xml',
        'https://www.aljazeera.com/xml/rss/all.xml',
    ]
    
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:1]:
                title = entry.get('title', '').strip()
                link = entry.get('link', '')
                description = entry.get('summary', '')[:200]
                description = re.sub(r'<[^>]+>', '', description)
                
                if title and link and len(title) > 20:
                    story_id = title[:60]
                    if story_id not in processed:
                        articles.append({
                            'title': title,
                            'url': link,
                            'description': description,
                            'source': feed.feed.get('title', 'News')[:25]
                        })
        except Exception as e:
            print(f"⚠️ Feed error: {e}")
    
    return articles[:1]

def get_images(title):
    images = []
    # Simple fallback images
    fallback_images = [
        'https://images.pexels.com/photos/6071605/pexels-photo-6071605.jpeg',
        'https://images.pexels.com/photos/1181467/pexels-photo-1181467.jpeg',
        'https://images.pexels.com/photos/210607/pexels-photo-210607.jpeg'
    ]
    
    for i, img_url in enumerate(fallback_images[:2]):
        images.append({
            'url': img_url,
            'alt': f"News image {i+1}",
            'caption': title[:40],
            'credit': 'Pexels'
        })
    return images

def write_short_article(title, description):
    current_date = datetime.now().strftime("%B %d, %Y")
    
    prompt = f"""Write a short news article about: {title}

Context: {description}

Write 4 paragraphs:
1. Introduction (2-3 sentences)
2. Key details (2-3 sentences)
3. Analysis (2-3 sentences)
4. Conclusion (2-3 sentences)

Keep it under 500 words. Write directly without markdown."""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            timeout=60
        )
        article = response.choices[0].message.content
        return article
    except Exception as e:
        print(f"AI Error: {e}")
        return f"<p>{description if description else title}</p><p>Stay tuned for updates on this developing story.</p>"

def post_to_blogger(service, title, content, images, source):
    current_date = datetime.now().strftime("%B %d, %Y")
    clean_title = title.replace('<', '&lt;').replace('>', '&gt;')
    
    images_html = ""
    for img in images[:2]:
        images_html += f'<img src="{img["url"]}" alt="{img["alt"]}" style="width:100%; max-width:600px; margin:15px 0;">'
    
    html = f"""<!DOCTYPE html>
<html>
<head><title>{clean_title[:60]}</title></head>
<body>
<h1>{clean_title}</h1>
<p><strong>📅 {current_date}</strong> | 📰 {source}</p>
{images_html}
<div>{content.replace(chr(10), '<br>')}</div>
<hr>
<p>© {datetime.now().year} News Analysis</p>
</body>
</html>"""
    
    post = service.posts().insert(
        blogId=BLOG_ID,
        body={'title': clean_title[:60], 'content': html},
        isDraft=False
    ).execute()
    print(f"✅ Published: {post.get('url')}")
    return post

def main():
    print("="*40)
    print(f"🤖 News Bot Running at {datetime.now().strftime('%H:%M:%S')}")
    
    articles = fetch_news()
    if not articles:
        print("📭 No new stories")
        return
    
    for article in articles:
        story_id = article['title'][:60]
        processed = load_processed()
        if story_id in processed:
            continue
        
        print(f"📰 Found: {article['title'][:50]}...")
        print("🖼️ Getting images...")
        images = get_images(article['title'])
        
        print("✍️ Writing article...")
        content = write_short_article(article['title'], article.get('description', ''))
        
        service = google_login()
        if service:
            post_to_blogger(service, article['title'], content, images, article['source'])
            processed.add(story_id)
            save_processed(processed)
            print("✅ Published successfully!")
        break

if __name__ == "__main__":
    main()