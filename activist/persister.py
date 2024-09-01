import sqlite3
from pathlib import Path
import logging
from typing import List, Tuple, Optional

LOGGER = logging.getLogger(__name__)


class CommentDatabase:
    def __init__(self, db_path: Path) -> None:
        """Initialize the CommentDatabase with the provided database path.

        Args:
            db_path (Path): The path to the SQLite database file.
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        self.initialize()

    def initialize(self) -> None:
        """Create necessary tables if they do not exist."""
        LOGGER.info("Initializing database tables.")

        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            link TEXT NOT NULL UNIQUE,
            summary TEXT,
            published DATETIME
        )
        ''')

        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS commentaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER,
            commentary TEXT NOT NULL,
            FOREIGN KEY(article_id) REFERENCES articles(id)
        )
        ''')

        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commentary_id INTEGER,
            status TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(commentary_id) REFERENCES commentaries(id)
        )
        ''')

        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commentary_id INTEGER,
            mastodon_id TEXT,
            posted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(commentary_id) REFERENCES commentaries(id)
        )
        ''')

        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER,
            reply TEXT NOT NULL,
            parent_reply_id INTEGER,
            FOREIGN KEY(post_id) REFERENCES posts(id),
            FOREIGN KEY(parent_reply_id) REFERENCES replies(id)
        )
        ''')

        self.conn.commit()

    def add_article(self, title: str, link: str, summary: str, published: str) -> None:
        """Add a new article to the database.

        Args:
            title (str): The title of the article.
            link (str): The link to the article.
            summary (str): The summary of the article.
            published (str): The published date of the article.
        """
        self.cursor.execute(
            'INSERT INTO articles (title, link, summary, published) VALUES (?, ?, ?, ?)',
            (title, link, summary, published)
        )
        self.conn.commit()

    def add_commentary(self, article_id: int, commentary: str) -> None:
        """Add a new commentary to an article.

        Args:
            article_id (int): The ID of the article.
            commentary (str): The commentary text.
        """
        self.cursor.execute(
            'INSERT INTO commentaries (article_id, commentary) VALUES (?, ?)',
            (article_id, commentary)
        )
        self.conn.commit()

    def add_approval(self, commentary_id: int, status: str) -> None:
        """Add an approval status to a commentary.

        Args:
            commentary_id (int): The ID of the commentary.
            status (str): The approval status.
        """
        self.cursor.execute(
            'INSERT INTO approvals (commentary_id, status) VALUES (?, ?)',
            (commentary_id, status)
        )
        self.conn.commit()

    def add_post(self, commentary_id: int, mastodon_id: str) -> None:
        """Add a new post to the database.

        Args:
            commentary_id (int): The ID of the commentary.
            mastodon_id (str): The Mastodon ID of the post.
        """
        self.cursor.execute(
            'INSERT INTO posts (commentary_id, mastodon_id) VALUES (?, ?)',
            (commentary_id, mastodon_id)
        )
        self.conn.commit()

    def add_reply(self, post_id: int, reply: str, parent_reply_id: Optional[int] = None) -> None:
        """Add a reply to a post.

        Args:
            post_id (int): The ID of the post.
            reply (str): The reply text.
            parent_reply_id (Optional[int]): The ID of the parent reply, if any. Defaults to None.
        """
        self.cursor.execute(
            'INSERT INTO replies (post_id, reply, parent_reply_id) VALUES (?, ?, ?)',
            (post_id, reply, parent_reply_id)
        )
        self.conn.commit()

    def get_approved_commentaries(self) -> List[Tuple[int, str]]:
        """Fetch commentaries that are not yet approved.

        Returns:
            List[Tuple[int, str]]: A list of tuples containing the ID and commentary text of unapproved commentaries.
        """
        self.cursor.execute(
            'SELECT id, commentary FROM commentaries WHERE id NOT IN (SELECT commentary_id FROM approvals)'
        )
        commentaries_to_approve = self.cursor.fetchall()
        return commentaries_to_approve


if __name__ == "__main__":
    db_path = Path("comments.db")
    comment_db = CommentDatabase(db_path)

    # Example usage
    comment_db.add_article("Sample Title", "http://example.com", "Sample summary", "2023-07-28")
    comment_db.add_commentary(1, "This is a commentary.")
    comment_db.add_approval(1, "approved")
    comment_db.add_post(1, "mastodon123")
    comment_db.add_reply(1, "This is a reply.")
    unapproved_commentaries = comment_db.get_approved_commentaries()
    print(unapproved_commentaries)
