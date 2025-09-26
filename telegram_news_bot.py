#!/usr/bin/env python3
"""
Telegram Channel News Bot - Enhanced Version
- Scrapes every hour for better performance
- Sends only high-impact articles (score 7+)
- Better duplicate detection
- Optimized for GitHub hosting
"""

import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime, timedelta
import re
import sqlite3
from dataclasses import dataclass
from typing import List, Set
import asyncio
import hashlib
import os

# For Telegram bot
try:
    import telegram
    from telegram import Bot
    TELEGRAM_AVAILABLE = True
except ImportError:
    print("❌ Install python-telegram-bot: pip install python-telegram-bot")
    TELEGRAM_AVAILABLE = False

@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    published_time: str
    importance_score: int
    content_hash: str = ""  # For better duplicate detection

class TelegramChannelNewsBot:
    def __init__(self, bot_token: str = None, channel_username: str = None):
        """Initialize the Telegram channel news bot"""
        
        # Get credentials from environment or user input
        self.bot_token = bot_token or os.getenv('TELEGRAM_BOT_TOKEN')
        self.channel_username = channel_username or os.getenv('TELEGRAM_CHANNEL_USERNAME')
        
        if not self.bot_token or not self.channel_username:
            self.bot_token, self.channel_username = self.get_channel_credentials()
        
        # Ensure channel username starts with @
        if not self.channel_username.startswith('@'):
            self.channel_username = '@' + self.channel_username
        
        # Initialize Telegram bot
        if TELEGRAM_AVAILABLE:
            self.bot = Bot(token=self.bot_token)
            print("✅ Telegram bot initialized")
        else:
            print("❌ Telegram bot not available")
            exit(1)
        
        # Enhanced news sources (reduced for better performance)
        self.news_sources = {
            # Top Indian Tech Sources
            'Economic Times Tech': 'https://economictimes.indiatimes.com/tech/rss/feedsdefault.cms',
            'LiveMint Tech': 'https://www.livemint.com/rss/technology',
            'Inc42': 'https://inc42.com/feed/',
            'YourStory': 'https://yourstory.com/feed',
            'MoneyControl Tech': 'https://www.moneycontrol.com/rss/technology.xml',
            
            # Top Global Tech Sources
            'TechCrunch': 'https://feeds.feedburner.com/TechCrunch/',
            'The Verge': 'https://www.theverge.com/rss/index.xml',
            'Ars Technica': 'http://feeds.arstechnica.com/arstechnica/index/',
            'VentureBeat': 'https://feeds.feedburner.com/venturebeat/SZYF',
            
            # Market News
            'Reuters Tech': 'https://feeds.reuters.com/reuters/technologyNews',
            'Bloomberg Tech': 'https://feeds.bloomberg.com/technology/news.rss',
            'CNBC Tech': 'https://www.cnbc.com/id/19854910/device/rss/rss.html',
            
            # Breaking News
            'BBC Tech': 'http://feeds.bbci.co.uk/news/technology/rss.xml',
            'Times of India Tech': 'https://timesofindia.indiatimes.com/rssfeeds/1081479906.cms',
            
            # Specialized
            'CoinDesk': 'https://feeds.feedburner.com/CoinDesk',
        }
        
        # High-impact keywords (streamlined)
        self.high_impact_keywords = {
            'breaking_urgent': [
                'breaking', 'urgent', 'alert', 'major announcement', 'massive', 'historic', 
                'unprecedented', 'emergency', 'just in', 'developing'
            ],
            
            'indian_companies': [
                'paytm', 'flipkart', 'zomato', 'swiggy', 'byju', 'oyo', 'ola', 'phonepe', 'razorpay', 
                'cred', 'dream11', 'nykaa', 'tcs', 'infosys', 'wipro', 'reliance', 'jio', 'airtel'
            ],
            
            'global_tech_giants': [
                'apple', 'google', 'microsoft', 'amazon', 'meta', 'facebook', 'tesla', 
                'nvidia', 'openai', 'chatgpt', 'netflix', 'uber', 'airbnb'
            ],
            
            'high_impact_events': [
                'ipo', 'acquisition', 'merger', 'funding', 'bankruptcy', 'layoffs', 'hiring freeze',
                'data breach', 'hack', 'cyber attack', 'stock crash', 'market surge'
            ],
            
            'tech_breakthroughs': [
                'ai breakthrough', 'quantum computing', 'autonomous', 'electric vehicle',
                'cryptocurrency', 'bitcoin', 'ethereum', 'blockchain', '5g', 'metaverse'
            ]
        }
        
        # Track sent articles to avoid duplicates
        self.sent_articles_cache: Set[str] = set()
        
        # Setup database
        self.setup_database()
        self.load_sent_articles_cache()
        print(f"🚀 Enhanced Bot initialized for {self.channel_username}")
    
    def get_channel_credentials(self):
        """Get Telegram channel credentials from user input"""
        print("📢 Telegram Channel Setup")
        print("=" * 50)
        print("🛠️ You can also set environment variables:")
        print("   TELEGRAM_BOT_TOKEN=your_bot_token")
        print("   TELEGRAM_CHANNEL_USERNAME=@your_channel")
        print()
        
        bot_token = input("🔑 Enter bot token: ").strip()
        channel_username = input("📢 Enter channel username (@channel): ").strip()
        
        if not bot_token or not channel_username:
            print("❌ Both token and channel username required!")
            exit(1)
        
        return bot_token, channel_username
    
    def setup_database(self):
        """Setup SQLite database with better schema"""
        self.conn = sqlite3.connect('telegram_news.db', check_same_thread=False)
        cursor = self.conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS articles (
                content_hash TEXT PRIMARY KEY,
                url TEXT,
                title TEXT,
                source TEXT,
                published_time TEXT,
                importance_score INTEGER,
                scraped_at TEXT,
                sent_to_channel BOOLEAN DEFAULT FALSE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channel_stats (
                date TEXT PRIMARY KEY,
                articles_sent INTEGER DEFAULT 0,
                avg_importance REAL DEFAULT 0,
                top_story TEXT
            )
        ''')
        
        # Create indexes for better performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sent_channel ON articles(sent_to_channel)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_importance ON articles(importance_score)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON articles(created_at)')
        
        self.conn.commit()
    
    def load_sent_articles_cache(self):
        """Load recently sent articles to cache"""
        cursor = self.conn.cursor()
        # Load articles sent in last 7 days
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        cursor.execute('''
            SELECT content_hash FROM articles 
            WHERE sent_to_channel = 1 AND created_at > ?
        ''', (week_ago,))
        
        self.sent_articles_cache = {row[0] for row in cursor.fetchall()}
        print(f"📚 Loaded {len(self.sent_articles_cache)} sent articles to cache")
    
    def create_content_hash(self, title: str, url: str) -> str:
        """Create hash for duplicate detection"""
        # Clean title for better duplicate detection
        clean_title = re.sub(r'[^\w\s]', '', title.lower()).strip()
        content = f"{clean_title}:{url}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def calculate_importance_score(self, title: str, content: str = '') -> int:
        """Enhanced importance scoring - only high-impact articles"""
        score = 0
        text = (title + ' ' + content).lower()
        title_lower = title.lower()
        
        # Keyword category scoring (higher thresholds)
        for category, keywords in self.high_impact_keywords.items():
            matches = sum(1 for keyword in keywords if keyword in text)
            if matches > 0:
                if category == 'breaking_urgent':
                    score += matches * 8  # Very high for breaking news
                elif category == 'high_impact_events':
                    score += matches * 6  # High for major events
                elif category in ['indian_companies', 'global_tech_giants']:
                    score += matches * 4  # Medium-high for company news
                elif category == 'tech_breakthroughs':
                    score += matches * 5  # High for tech breakthroughs
        
        # Title-specific bonuses (higher visibility)
        urgent_words = ['breaking', 'urgent', 'major', 'massive', 'historic', 'unprecedented']
        if any(word in title_lower for word in urgent_words):
            score += 8
        
        company_words = ['apple', 'google', 'microsoft', 'amazon', 'tesla', 'openai', 'meta']
        if any(word in title_lower for word in company_words):
            score += 6
        
        event_words = ['ipo', 'acquisition', 'merger', 'funding', 'layoffs', 'hack', 'breach']
        if any(word in title_lower for word in event_words):
            score += 7
        
        # Indian relevance bonus
        if any(word in title_lower for word in ['india', 'indian', 'rupee', 'mumbai', 'delhi']):
            score += 3
        
        return min(score, 15)  # Higher cap for better articles
    
    def scrape_rss_feed(self, source_name: str, feed_url: str) -> List[NewsItem]:
        """Scrape RSS feed with better error handling"""
        articles = []
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(feed_url, headers=headers, timeout=15)
            response.raise_for_status()
            
            try:
                soup = BeautifulSoup(response.content, 'xml')
            except:
                soup = BeautifulSoup(response.content, 'html.parser')
            
            items = soup.find_all('item')[:10]  # Limit to recent 10 items
            
            for item in items:
                try:
                    title_elem = item.find('title')
                    link_elem = item.find('link')
                    desc_elem = item.find('description')
                    
                    if title_elem and link_elem:
                        title = title_elem.get_text().strip()
                        url = link_elem.get_text().strip()
                        description = desc_elem.get_text().strip() if desc_elem else ''
                        
                        # Clean description
                        description = re.sub(r'<[^>]+>', '', description)
                        
                        # Calculate importance
                        importance = self.calculate_importance_score(title, description)
                        
                        # Only high-impact articles (score 7+)
                        if importance >= 7:
                            content_hash = self.create_content_hash(title, url)
                            
                            # Skip if already sent
                            if content_hash not in self.sent_articles_cache:
                                articles.append(NewsItem(
                                    title=title,
                                    url=url,
                                    source=source_name,
                                    published_time=datetime.now().strftime('%Y-%m-%d %H:%M'),
                                    importance_score=importance,
                                    content_hash=content_hash
                                ))
                            
                except Exception as e:
                    continue
            
            if articles:
                print(f"   ✅ {source_name}: {len(articles)} high-impact articles")
            
        except Exception as e:
            print(f"   ❌ {source_name}: {str(e)[:50]}...")
        
        return articles
    
    def save_article(self, article: NewsItem, sent_to_channel: bool = False):
        """Save article to database"""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO articles 
            (content_hash, url, title, source, published_time, importance_score, scraped_at, sent_to_channel)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            article.content_hash,
            article.url,
            article.title,
            article.source,
            article.published_time,
            article.importance_score,
            datetime.now().isoformat(),
            sent_to_channel
        ))
        self.conn.commit()
    
    async def send_to_channel(self, article: NewsItem):
        """Send high-impact article to channel"""
        try:
            # Determine urgency level
            if article.importance_score >= 12:
                emoji = "🚨"
                urgency = "URGENT"
                pin_message = True
            elif article.importance_score >= 9:
                emoji = "📢"
                urgency = "BREAKING"
                pin_message = False
            else:
                emoji = "⚡"
                urgency = "HIGH IMPACT"
                pin_message = False
            
            # Create formatted message
            message = f"""{emoji} **{urgency}**

**{article.title}**

📍 *{article.source}*
⭐ Impact Score: {article.importance_score}/15
🕐 {article.published_time}

🔗 [Read Article]({article.url})

#TechNews #Breaking #HighImpact"""
            
            # Send to channel
            sent_message = await self.bot.send_message(
                chat_id=self.channel_username,
                text=message,
                parse_mode='Markdown',
                disable_web_page_preview=False
            )
            
            # Pin very urgent messages
            if pin_message:
                try:
                    await self.bot.pin_chat_message(
                        chat_id=self.channel_username,
                        message_id=sent_message.message_id,
                        disable_notification=False
                    )
                except:
                    pass
            
            # Add to cache
            self.sent_articles_cache.add(article.content_hash)
            
            print(f"   📤 Sent: {article.title[:50]}... [Score: {article.importance_score}]")
            return True
            
        except Exception as e:
            print(f"   ❌ Send error: {e}")
            return False
    
    async def scrape_all_sources(self) -> List[NewsItem]:
        """Scrape all sources for high-impact articles"""
        all_articles = []
        
        print("🔍 Scanning for HIGH-IMPACT news...")
        
        for i, (source_name, feed_url) in enumerate(self.news_sources.items()):
            print(f"   ({i+1}/{len(self.news_sources)}) {source_name}")
            
            articles = self.scrape_rss_feed(source_name, feed_url)
            
            if articles:
                all_articles.extend(articles)
                
                # Save to database
                for article in articles:
                    self.save_article(article)
            
            # Small delay between requests
            await asyncio.sleep(0.5)
        
        # Sort by importance (highest first)
        all_articles.sort(key=lambda x: x.importance_score, reverse=True)
        
        # Return top 10 to avoid spam
        return all_articles[:10]
    
    async def send_startup_message(self):
        """Send bot startup notification"""
        try:
            message = """🚀 **High-Impact Tech News Bot Started!**

📊 **What you get:**
• ⚡ Only HIGH-IMPACT articles (score 7+)
• 🇮🇳 Indian + Global Tech News
• 💰 Major Market Events
• 🤖 AI & Crypto Breakthroughs
• 📢 Breaking News Alerts

🔄 **Updates:** Every hour
🎯 **Quality:** No spam, only important news
⭐ **Scoring:** Impact-based filtering

#HighImpact #TechNews #QualityNews"""
            
            await self.bot.send_message(
                chat_id=self.channel_username,
                text=message,
                parse_mode='Markdown'
            )
                
        except Exception as e:
            print(f"❌ Startup message error: {e}")
    
    async def run_monitoring(self):
        """Run hourly monitoring for high-impact news"""
        print("🚀 Starting HIGH-IMPACT news monitoring...")
        print(f"📢 Channel: {self.channel_username}")
        print(f"⏰ Checking every 60 minutes for quality articles")
        
        # Send startup message
        await self.send_startup_message()
        
        while True:
            try:
                current_time = datetime.now()
                time_str = current_time.strftime('%H:%M:%S')
                print(f"\n⏰ HIGH-IMPACT News Check at {time_str}")
                
                # Scrape for high-impact articles
                high_impact_articles = await self.scrape_all_sources()
                
                if high_impact_articles:
                    print(f"📊 Found {len(high_impact_articles)} HIGH-IMPACT articles")
                    
                    # Send ALL high-impact articles (they're already filtered)
                    sent_count = 0
                    for article in high_impact_articles:
                        success = await self.send_to_channel(article)
                        if success:
                            sent_count += 1
                            self.save_article(article, sent_to_channel=True)
                        
                        # Small delay between messages
                        await asyncio.sleep(2)
                    
                    print(f"📤 Sent {sent_count} high-impact articles to channel")
                    
                    # Show summary
                    if high_impact_articles:
                        print(f"\n📈 Top Stories Sent:")
                        for i, article in enumerate(high_impact_articles[:3], 1):
                            print(f"   {i}. [{article.importance_score}/15] {article.title[:60]}...")
                
                else:
                    print("😴 No high-impact articles found this hour")
                
                # Clean old cache (keep last 3 days)
                if len(self.sent_articles_cache) > 1000:
                    print("🧹 Cleaning old article cache...")
                    # Keep recent articles and rebuild cache from DB
                    self.load_sent_articles_cache()
                
                print(f"⏱️  Next HIGH-IMPACT check in 1 hour...")
                await asyncio.sleep(3600)  # Wait 1 hour
                
            except KeyboardInterrupt:
                print("\n👋 Monitoring stopped by user")
                try:
                    await self.bot.send_message(
                        chat_id=self.channel_username,
                        text="⏸️ **Bot offline for maintenance**\nHigh-impact news will resume shortly!",
                        parse_mode='Markdown'
                    )
                except:
                    pass
                break
                
            except Exception as e:
                print(f"\n❌ Error: {e}")
                print("⏰ Retrying in 5 minutes...")
                await asyncio.sleep(300)  # Wait 5 minutes on error

async def main():
    """Main function"""
    print("🚀 High-Impact Telegram News Channel Bot")
    print("⚡ Delivers only the most important tech news!")
    print()
    
    # Initialize bot (will get credentials if not in env)
    bot = TelegramChannelNewsBot()
    
    print(f"\n📢 Starting monitoring for: {bot.channel_username}")
    print("⏹️  Press Ctrl+C to stop")
    
    try:
        await bot.run_monitoring()
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")

if __name__ == "__main__":
    asyncio.run(main())