"""Header, sidebar and banner data shared by every page."""
from django.urls import reverse

from accounts.auth import current_user

from . import data

# Sidebar: (page key, URL name, icon, label), or a heading
NAV = [
    ("landing", "dashboard:home", "globe", "Home"),
    ("dashboard", "dashboard:overview", "bar-chart-2", "Executive dashboard"),
    ("analytics", "dashboard:analytics", "activity", "Climate analytics"),
    ("monitoring", "dashboard:monitor", "wifi", "Live monitor"),
    ("data", "dashboard:data", "database", "Data explorer and upload"),
    ("Big data infrastructure",),
    ("hadoop", "dashboard:hadoop", "server", "Hadoop and HDFS cluster"),
    ("ml", "dashboard:ml", "cpu", "ML models and forecasts"),
    ("alerts", "dashboard:alerts", "alert-triangle", "Alert management"),
    ("reports", "dashboard:reports", "file-text", "Reports and export"),
    ("Administration",),
    ("rbac", "accounts:users", "users", "Users and roles"),
    ("support", "dashboard:support", "help-circle", "Feedback and support"),
    ("status", "dashboard:status", "shield-check", "System status"),
    ("architecture", "dashboard:architecture", "code", "System architecture"),
    ("settings", "accounts:settings", "settings", "Account settings"),
]


def _nav(active_alerts):
    items = []
    for entry in NAV:
        if len(entry) == 1:
            items.append({"heading": entry[0]})
        else:
            key, url_name, icon, label = entry
            items.append({"key": key, "url": reverse(url_name), "icon": icon, "label": label,
                          "badge": active_alerts if key == "alerts" and active_alerts else None})
    return items


def chrome(request):
    """Banner everywhere; chrome when signed in."""
    if request.path.startswith(("/static/", "/api/")):
        return {}
    context = {"maintenance": data.maintenance()}
    if not request.path.startswith("/dashboard/"):
        return context
    user = current_user(request)
    if not user:
        return context
    notifications = data.notifications(user)
    unread = sum(1 for item in notifications if not item["read"])
    context.update({
        "user": user,
        "nav": _nav(data.active_alert_count()),
        "notifications": notifications,
        "unread": "9+" if unread > 9 else unread,
        "sidebar": data.sidebar_cluster(),
    })
    return context
