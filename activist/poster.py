# Posting approved comments to Mastodon
from mastodon import Mastodon

from activist.persister import get_approved_commentaries, add_post, add_reply


def post_to_mastodon(comment, article_link, api):
    api.status_post(f"{comment}\nRead more: {article_link}")

def post_all_comments():
    mastodon_api = Mastodon(
        access_token='YOUR_ACCESS_TOKEN',
        api_base_url='https://mastodon.social'
    )

    approved_comments = get_approved_comments()
    for comment, article_link in approved_comments:
        post_to_mastodon(comment, article_link, mastodon_api)


def post_all_replies():
    mastodon_api = Mastodon(
        access_token='YOUR_ACCESS_TOKEN',
        api_base_url='https://mastodon.social'
    )
    approved_commentaries= get_approved_commentaries()
    for commentary_id, commentary in approved_commentaries:
        status = mastodon_api.status_post(commentary)
        add_post(commentary_id, status['id'])

    # Fetching replies for a post
    post_id = 1  # Example post ID
    replies = mastodon_api.status_replies(post_id)

    for reply in replies:
        add_reply(post_id, reply['content'], reply.get('in_reply_to_id'))
