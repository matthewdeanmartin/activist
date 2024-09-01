import asyncio
import feedparser
import httpx
from typing import List, Dict
from bs4 import BeautifulSoup
import html2text
import logging

LOGGER = logging.getLogger(__name__)


async def fetch_rss_feed(url: str) -> List[Dict[str, str]]:
    """
    Fetches RSS feed from the given URL.

    Args:
        url (str): The URL of the RSS feed.

    Returns:
        List[Dict[str, str]]: A list of dictionaries containing article details.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
    feed = feedparser.parse(response.text)
    articles: List[Dict[str, str]] = []
    for entry in feed.entries:
        articles.append({
            'title': entry.title,
            'link': entry.link,
            'summary': entry.summary,
            'published': entry.published
        })
    LOGGER.info("Fetched %d articles from RSS feed at %s", len(articles), url)
    return articles


async def fetch_full_article_html(url: str) -> str:
    """
    Fetches the full HTML content of the article from the given URL.

    Args:
        url (str): The URL of the article.

    Returns:
        str: The HTML content of the article.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
    LOGGER.info("Fetched full HTML content from %s", url)
    return response.text


def extract_plain_text_from_html(html_content: str) -> str:
    """
    Extracts plain text from HTML content.

    Args:
        html_content (str): The HTML content of the article.

    Returns:
        str: The plain text extracted from the HTML.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    text_maker = html2text.HTML2Text()
    text_maker.ignore_links = True
    plain_text = text_maker.handle(str(soup))
    return plain_text


async def process_article(article: Dict[str, str]) -> Dict[str, str]:
    """
    Processes an article by fetching its full HTML content and converting it to plain text.

    Args:
        article (Dict[str, str]): The article dictionary.

    Returns:
        Dict[str, str]: The article dictionary with an additional 'full_text' field.
    """
    html_content = await fetch_full_article_html(article['link'])
    plain_text = extract_plain_text_from_html(html_content)
    article['full_text'] = plain_text
    return article


async def fetch_and_process_rss_feeds(urls: List[str]) -> List[Dict[str, str]]:
    """
    Fetches and processes multiple RSS feeds.

    Args:
        urls (List[str]): List of RSS feed URLs.

    Returns:
        List[Dict[str, str]]: A list of processed articles from all feeds.
    """
    articles: List[Dict[str, str]] = []
    for url in urls:
        feed_articles = await fetch_rss_feed(url)
        processed_articles = await asyncio.gather(*[process_article(article) for article in feed_articles])
        articles.extend(processed_articles)
    return articles


def format_comment(article: Dict[str, str]) -> str:
    """
    Formats an article into a comment string including the full text.

    Args:
        article (Dict[str, str]): The article dictionary containing 'title', 'link', 'summary', 'published', and 'full_text'.

    Returns:
        str: The formatted comment string.
    """
    return f"{article['title']}\n\n{article['full_text']}\nRead more: {article['link']}"


if __name__ == "__main__":
    # Example usage
    async def main():
        rss_urls = [
            "https://example.com/rss1",
            "https://example.com/rss2",
            "https://example.com/rss3"
        ]
        articles = await fetch_and_process_rss_feeds(rss_urls)

        # Separate out articles and just the plain text
        comments = [format_comment(article) for article in articles]

        # Example usage: add articles to database and add comments to queue
        # for article in articles:
        #     comment_db.add_article(article['title'], article['link'], article['summary'], article['published'], article['full_text'])
        # add_to_queue(comments)


    asyncio.run(main())
