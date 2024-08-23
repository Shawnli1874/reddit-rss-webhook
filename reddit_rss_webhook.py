import os
import requests
import feedparser
import logging
import time
from datetime import datetime
from dateutil import parser as date_parser
from bs4 import BeautifulSoup
import pandas as pd
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 从 .env 文件中获取配置参数
subreddit = os.getenv('SUBREDDIT', 'all')
keyword = os.getenv('KEYWORD', '')
webhook_url = os.getenv('WEBHOOK_URL')
bearer_token = os.getenv('BEARER_TOKEN')
test_mode = os.getenv('TEST_MODE', 'False').lower() == 'true'
sent_posts_file = os.getenv('SENT_POSTS_FILE', 'sent_posts.xlsx')

# 生成 RSS feed URL
if keyword:
    rss_url = f'https://www.reddit.com/r/{subreddit}/search.rss?q={keyword}&restrict_sr=1&sort=new'
else:
    rss_url = f'https://www.reddit.com/r/{subreddit}/new/.rss'

# 初始化已发送的帖子链接
def load_sent_links():
    if os.path.exists(sent_posts_file):
        df = pd.read_excel(sent_posts_file)
        return set(df['Link'].dropna())
    return set()

# 保存帖子数据到 Excel 文件
def save_post_data(entry_data):
    if os.path.exists(sent_posts_file):
        df = pd.read_excel(sent_posts_file)
        df = pd.concat([df, pd.DataFrame([entry_data])], ignore_index=True)
    else:
        df = pd.DataFrame([entry_data])
    df.to_excel(sent_posts_file, index=False)

# 上次发送的帖子链接，避免重复发送
last_post_links = load_sent_links()

def clean_html(raw_html):
    "使用 BeautifulSoup 清理 HTML 内容，提取纯文本"
    soup = BeautifulSoup(raw_html, 'html.parser')
    return soup.get_text(separator="\n").strip()

def fetch_and_send_posts():
    logging.info(f'Fetching RSS feed from: {rss_url}')

    # 使用 requests 获取 RSS feed
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(rss_url, headers=headers, timeout=10)
        response.raise_for_status()  # 检查是否返回了一个 HTTP 错误
        logging.info('RSS feed fetched successfully.')
    except requests.exceptions.RequestException as e:
        logging.error(f'Failed to fetch RSS feed: {e}')
        return

    # 使用 feedparser 解析 RSS 数据
    feed = feedparser.parse(response.content)

    # 设置要发送的最大帖子数（测试模式为 3，正常模式为无限）
    max_posts = 3 if test_mode else float('inf')

    # 遍历所有的帖子条目
    post_count = 0
    if feed.entries:
        logging.info(f'Found {len(feed.entries)} entries.')
        for entry in feed.entries:
            if entry.link not in last_post_links and post_count < max_posts:
                entry_data = {
                    'Post Type': 'Submission',
                    'Title': entry.title,
                    'Author': entry.author.replace('/u/', '') if 'author' in entry else 'Unknown',
                    'Content': clean_html(entry.summary) if 'summary' in entry else 'No content available',
                    'Published Time': entry.published,
                    'Link': entry.link
                }

                # 解析 ISO 8601 时间格式并转换为所需格式
                entry_data['Published Time'] = date_parser.parse(entry_data['Published Time']).strftime('%Y-%m-%d %H:%M:%S')

                # 发送数据到 webhook
                try:
                    payload = {
                        'content': "New Post Alert!",
                        'embeds': [
                            {
                                'title': entry_data['Title'],
                                'url': entry_data['Link'],
                                'author': entry_data['Author'],
                                'description': f"Posted by {entry_data['Author']} on {entry_data['Published Time']}\n\nContent:\n{entry_data['Content']}",
                                'timestamp': entry_data['Published Time']
                            }
                        ]
                    }
                    headers = {
                        'Authorization': f'Bearer {bearer_token}',
                        'Content-Type': 'application/json'
                    }
                    webhook_response = requests.post(webhook_url, json=payload, headers=headers)
                    webhook_response.raise_for_status()
                    logging.info(f"Data sent to webhook successfully for post: {entry_data['Title']}")
                    last_post_links.add(entry.link)
                    save_post_data(entry_data)  # 保存已发送的帖子数据
                    post_count += 1  # 增加已发送的帖子计数
                    time.sleep(2)  # 每次发送消息后暂停2秒
                except requests.exceptions.RequestException as e:
                    logging.error(f'Failed to send data to webhook: {e}')
    else:
        logging.info('No entries found in the RSS feed.')

if __name__ == "__main__":
    if test_mode:
        fetch_and_send_posts()  # 测试模式下只执行一次
    else:
        while True:
            fetch_and_send_posts()
            time.sleep(3600)  # 每60分钟检查一次