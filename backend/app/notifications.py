"""System notifications shown under the dashboard's bell."""
import datetime

from .db import db


def notify(text, user_id=None):
    """Sends to one user, or to everyone when user_id is None."""
    db.notifications.insert_one({
        "text": text,
        "user_id": user_id,
        "read_by": [],
        "created_at": datetime.datetime.now(datetime.timezone.utc),
    })
