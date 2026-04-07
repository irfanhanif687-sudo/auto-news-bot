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

# ========== RSS FEEDS (Sab tarah ki news ke liye) ==========
RSS_FEEDS = [
    'http://feeds.bbci.co.uk/news/world/rss.xml',
    'http://feeds.bbci.co.uk/news/business/rss.xml',
    'http://feeds.bbci.co.uk/sport/rss.xml',
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
                
                # Sirf bakwas news skip karo
                skip_words = ['beer', 'balloon', 'mortgage', 'recipe', 'cook', 'celebrity', 'gossip']
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

def detect_news_category(title):
    """News ki category detect karo"""
    title_lower = title.lower()
    
    if any(word in title_lower for word in ['football', 'soccer', 'champions league', 'barcelona', 'real madrid', 'premier league', 'match', 'goal', 'win', 'defeat']):
        return 'sports'
    elif any(word in title_lower for word in ['iran', 'israel', 'trump', 'war', 'attack', 'missile', 'strike', 'military', 'consulate']):
        return 'politics'
    elif any(word in title_lower for word in ['oil', 'price', 'economy', 'market', 'inflation', 'stock', 'trade']):
        return 'business'
    elif any(word in title_lower for word in ['train', 'crash', 'accident', 'killed', 'dead', 'collision', 'death']):
        return 'accident'
    else:
        return 'general'

def write_human_article(title, description, source, retry_count=0):
    """Category ke hisaab se humanised article"""
    current_date = datetime.now().strftime("%B %d, %Y")
    category = detect_news_category(title)
    
    # Category-specific prompts
    if category == 'sports':
        prompt = f"""Write a SPORTS NEWS article like a real sports journalist.

TITLE: {title}
DATE: {current_date}
SOURCE: {source}
CONTEXT: {description[:400]}

Write like ESPN or BBC Sport:
- Start with the key moment: "In a stunning match at Camp Nou..."
- Add match atmosphere: crowd reaction, tension, excitement
- Mention players, managers, tactics
- Include quotes from players or managers (realistic)
- Talk about what this means for the tournament/league
- End with what's next for both teams

Be energetic, passionate, and human. 500-800 words. Write now:"""
    
    elif category == 'politics':
        prompt = f"""Write a POLITICS NEWS article like a real journalist.

TITLE: {title}
DATE: {current_date}
SOURCE: {source}
CONTEXT: {description[:400]}

Write like BBC News or Al Jazeera:
- Start with what happened, where, when
- Add official statements and reactions
- Include witness or expert quotes
- Explain why this matters
- What happens next

Be factual but human. 500-800 words. Write now:"""
    
    elif category == 'business':
        prompt = f"""Write a BUSINESS NEWS article like a real financial journalist.

TITLE: {title}
DATE: {current_date}
SOURCE: {source}
CONTEXT: {description[:400]}

Write like Bloomberg or Financial Times:
- Start with the key economic impact
- Add numbers, percentages, trends
- Include analyst quotes
- Explain how this affects ordinary people
- Future outlook

Be clear and informative. 500-800 words. Write now:"""
    
    elif category == 'accident':
        prompt = f"""Write a NEWS ARTICLE about this accident/incident.

TITLE: {title}
DATE: {current_date}
SOURCE: {source}
CONTEXT: {description[:400]}

Write like a local news reporter:
- Start with what happened, where, when
- Add official statements from police/authorities
- Include witness quotes (realistic)
- Mention casualties, response, investigation
- End with what happens next

Be respectful and factual. 500-800 words. Write now:"""
    
    else:
        prompt = f"""Write a HUMANISED news article.

TITLE: {title}
DATE: {current_date}
SOURCE: {source}
CONTEXT: {description[:400]}

Rules:
- Sound like a real person, not AI
- Add specific details and realistic quotes
- Short sentences, varied length
- Strong opening, natural ending
- NO placeholders like [LOCATION]
- 500-800 words

Write now:"""

    try:
        print(f"   ✍️ Writing {category} article (attempt {retry_count + 1})...")
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            timeout=180
        )
        article = response.choices[0].message.content
        
        word_count = len(article.split())
        print(f"   📊 Word count: {word_count}")
        
        # Check for placeholders
        if ('[LOCATION]' in article or '[DATE]' in article) and retry_count < 2:
            print(f"   ⚠️ Found placeholders, retrying...")
            time.sleep(5)
            return write_human_article(title, description, source, retry_count + 1)
        
        if word_count < 300 and retry_count < 2:
            print(f"   ⚠️ Too short ({word_count} words), retrying...")
            time.sleep(5)
            return write_human_article(title, description, source, retry_count + 1)
        
        return article
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        if retry_count < 2:
            print(f"   🔄 Retrying...")
            time.sleep(10)
            return write_human_article(title, description, source, retry_count + 1)
        return get_human_fallback(title, description, category)

def get_human_fallback(title, description, category):
    """Category-specific fallback - NO PLACEHOLDERS"""
    
    if category == 'sports':
        return f"""<p>In what fans are calling a thrilling encounter, {title[:80]} delivered all the drama and excitement expected from this fixture.</p>

<p>The atmosphere inside the stadium was electric from the first whistle. Supporters of both sides created a wall of sound that never let up throughout the 90 minutes.</p>

<p>Speaking after the match, the winning team's manager said: "The players gave everything tonight. I couldn't be prouder of their effort and commitment."</p>

<p>This result could have major implications for the tournament standings. Both teams will now turn their attention to their next fixtures, knowing that every point matters at this stage of the competition.</p>

<p>Football fans around the world will be watching closely to see how this result shapes the rest of the season.</p>"""
    
    elif category == 'accident':
        return f"""<p>Authorities have confirmed they are responding to an incident involving {title[:80]}.</p>

<p>Emergency services arrived at the scene quickly. Officials say an investigation is now underway to determine the full circumstances.</p>

<p>"Our thoughts are with everyone affected," a local official said. "We will release more information as soon as we have confirmed details."</p>

<p>Witnesses described hearing loud noises and seeing emergency vehicles rush to the location. The area remains cordoned off while investigators do their work.</p>

<p>This story is still developing. We will update as more official information becomes available.</p>"""
    
    else:
        return f"""<p>Here's what we know so far about {title[:80]}.</p>

<p>According to initial reports, this is a significant development that people are watching closely around the world.</p>

<p>Officials have confirmed they are aware of the situation and are monitoring it closely. More details are expected to emerge in the coming hours.</p>

<p>Our team is following this story and will bring you updates as soon as new information becomes available.</p>

<p>Check back later for the latest developments on this ongoing story.</p>"""

def post_to_blogger(service, title, content, images, source):
    current_date = datetime.now().strftime("%B %d, %Y")
    word_count = len(content.split())
    reading_time = max(4, round(word_count / 200))
    clean_title = title.replace('<', '&lt;').replace('>', '&gt;')
    
    slug = re.sub(r'[^a-z0-9]+', '-', clean_title.lower())[:60]
    current_url = f"https://newnews4public.blogspot.com/{datetime.now().year}/{datetime.now().month}/{slug}.html"
    
    images_html = ""
    for img in images:
        images_html += f'''
        <figure style="text-align: center; margin: 25px 0;">
            <img src="{img['url']}" alt="{img['alt'][:80]}" style="width:100%; max-width:750px; border-radius:12px;" loading="lazy">
            <figcaption style="font-size:12px; color:#666; margin-top:8px;">📷 {img['caption'][:70]} | Photo: {img['credit']}</figcaption>
        </figure>
        '''
    
    content_html = content.replace('\n\n', '</p><p>')
    content_html = f'<p>{content_html}</p>'
    content_html = content_html.replace('<p><h2>', '<h2>').replace('</h2></p>', '</h2>')
    
    category = detect_news_category(title)
    if category == 'sports':
        labels = ['Sports News', 'Football']
    elif category == 'politics':
        labels = ['World News', 'Politics']
    elif category == 'business':
        labels = ['Business News', 'Economy']
    else:
        labels = ['World News', 'Breaking News']
    
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
        .meta {{ color: #666; font-size: 13px; margin-bottom: 25px; padding-bottom: 15px; border-bottom: 1px solid #e0e0e0; display: flex; justify-content: space-between; flex-wrap: wrap; }}
        .article-content p {{ margin-bottom: 22px; text-align: justify; line-height: 1.7; }}
        hr {{ margin: 40px 0; border: none; height: 1px; background: #e0e0e0; }}
        @media (max-width: 600px) {{ body {{ padding: 15px; font-size: 16px; }} h1 {{ font-size: 28px; }} }}
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
        body={'title': clean_title[:70], 'content': html, 'labels': labels},
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
            print(f"   ⏭️ Already posted")
            continue
        
        print(f"\n📰 {article['title'][:70]}...")
        print(f"   Source: {article['source']}")
        print(f"   Category: {detect_news_category(article['title'])}")
        
        print(f"   🖼️ Getting images...")
        images = get_images(article['title'])
        
        print(f"   ✍️ Writing humanised article...")
        content = write_human_article(
            article['title'], 
            article.get('description', ''), 
            article['source']
        )
        
        word_count = len(content.split())
        print(f"   📝 Final: {word_count} words")
        
        service = google_login()
        if service:
            post_to_blogger(service, article['title'], content, images, article['source'])
            processed.add(story_id)
            save_processed(processed)
            print(f"   ✅ Published!")
        
        break

def run():
    print("""
    ╔══════════════════════════════════════════════════════════════════════╗
    ║      📰 HUMANISED NEWS BOT - ALL CATEGORIES (Sports/Politics/Business) ║
    ║                                                                      ║
    ║   ✓ Sports news (football, champions league, matches)               ║
    ║   ✓ Politics news (Iran, Israel, Trump, war)                        ║
    ║   ✓ Business news (oil, economy, prices)                            ║
    ║   ✓ Accidents and general news                                      ║
    ║   ✓ Humanised writing, no placeholders                              ║
    ║   ✓ Runs every 10 minutes                                           ║
    ╚══════════════════════════════════════════════════════════════════════╝
    """)
    
    print("✅ Bot is RUNNING")
    print("⏰ Runs every 10 minutes")
    print("🏆 Covers: Sports | Politics | Business | Accidents\n")
    
    check_and_post()

if __name__ == "__main__":
    run()
