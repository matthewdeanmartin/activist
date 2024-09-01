from activist.approver import approve_all_comments_ui
from activist.importer import fetch_rss_feed, format_comment
from activist.persister import add_to_queue
from activist.poster import post_all_comments

if __name__ == '__main__':
    command = "import"
    if command  == "import":
        rss_url = "https://example.com/rss"
        articles = fetch_rss_feed(rss_url)
        for article in articles:
            comment_db.add_article("Sample Title", "http://example.com", "Sample summary", "2023-07-28")
        comments = [format_comment(article) for article in articles]
        # Adding comments to the SQLite queue
        add_to_queue(comments)
    elif command == "approve":
        approve_all_comments_ui()
    elif command == "post":
        post_all_comments()



