# Activist

## Architecture

Transform Input Flow: Daily Data In -> Initial Post -> Moderator Bot -> Human Approval Queue. End of Program.

Publish Flow: New Post Approved -> Posted. End of Program

Like/Reply to Comments Flow: Fetch comments -> Is there #nobot? negative sentiment? 

    -> Generate likes -> Post likes    

    -> Generate Replies -> Moderator Bot -> Human Approval Queue. End of Program.

Follow Back Flow: Following max reached? -> Fetch followers -> Follow back unless #nobot in bio. End of Program.



## Initial Daily Data In
Just md and images that are added manual. Bot loops through folders with have date of YYYY-MM-DD.

This forms raw material for post idea.


## Initial Posts 
- Fetch RSS feed
- Convert RSS to comments
- Put comments into queue
- Human approves comments
- Bot posts comments with link to RSS article to Mastodon

## Follow up posts
- Fetch Mastodon Replies
- Bot create reply to reply
- Put into queue
- Approved by human
- Bot posts reply to Mastodon