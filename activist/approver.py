# Fetching comments from the SQLite queue for approval
from activist.persister import get_from_queue, approve_comment

def approve_all_comments_ui():
    comments_to_approve = get_from_queue()
    for comment_id, comment, article_link in comments_to_approve:
        print(f"Comment: {comment}\nLink: {article_link}")
        approval = input("Approve this comment? (y/n): ")
        if approval.lower() == 'y':
            approve_comment(comment_id)


    for commentary_id, commentary in commentaries_to_approve:
        print(f"Commentary: {commentary}")
        approval = input("Approve this commentary? (y/n): ")
        status = 'approved' if approval.lower() == 'y' else 'denied'
        add_approval(commentary_id, status)
