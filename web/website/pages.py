"""Website page list: slugs, titles, templates and old Webflow file names."""

# Service pages: slug -> (title, old file)
SERVICES = {
    "climate-analytics": ("Climate Analytics", "services/climate-resilient.html"),
    "climate-forecasts": ("Climate Forecasts", "services/organic-practices.html"),
    "alerts-notifications": ("Alerts & Notifications", "services/precision-farming.html"),
    "reports-export": ("Reports & Export", "services/supply-chain-support.html"),
    "live-monitoring": ("Live Monitoring", "services/sustainable-irrigation.html"),
    "big-data-processing": ("Big Data Processing", "services/technology-integration.html"),
}

# Access levels: slug -> (title, old file)
PLANS = {
    "public-visitor": ("Public Visitor", "pricing/starter-plan.html"),
    "analyst": ("Analyst", "pricing/growth-plan.html"),
    "administrator": ("Administrator", "pricing/enterprise-plan.html"),
}

# Access level cards on the Access page
PLAN_CARDS = [
    {"slug": "public-visitor", "title": "Public Visitor", "summary": "Read the website without an account",
     "price": "Open", "price_note": "to everyone", "featured": False,
     "can_do": ["Read about EarthScape", "See every service", "Read the blog", "Send a message"],
     "limits": ["No dashboard access", "No data exports", "No live readings", "No support tickets"]},
    {"slug": "analyst", "title": "Analyst", "summary": "Explore data and export results",
     "price": "Sign-in", "price_note": "required", "featured": True,
     "can_do": ["View all dashboards", "Export data files", "Follow alerts", "Raise support tickets"],
     "limits": ["No alert rule changes", "No data uploads", "No jobs or retraining", "No user management"]},
    {"slug": "administrator", "title": "Administrator", "summary": "Run the platform and its data",
     "price": "Admin", "price_note": "only", "featured": False,
     "can_do": ["Manage users and roles", "Set alert rules", "Upload data and run jobs", "Retrain models"],
     "limits": ["Sign-in limits still apply", "Passwords stay hidden", "Job results can’t be edited",
                "Past readings can’t be changed"]},
]


def plan_cards():
    """Cards with their colours."""
    cards = []
    for plan in PLAN_CARDS:
        # Featured card: yellow with a white button
        colours = ({"background": "#f6d987", "button": "white", "button_text": "black"} if plan["featured"]
                   else {"background": "white", "button": "black", "button_text": "white"})
        cards.append(dict(plan, **colours))
    return cards


# Blog posts: slug -> (title, old file)
POSTS = {
    "how-hadoop-processes-our-climate-data": ("How Hadoop Processes Our Climate Data",
                                              "blog/building-supply-chains-in-agriculture-with-new-technich.html"),
    "nasa-temperature-records-since-1880": ("What NASA Temperature Records Show Since 1880",
                                            "blog/data-driven-growth-for-every-acre-discover-how-smart-technologies.html"),
    "keeping-climate-data-safe": ("How We Keep Climate Data Safe and Available",
                                  "blog/emerging-trends-in-agricultural-technology-solutions-best-farming.html"),
    "live-air-quality-in-12-cities": ("How Live Readings Track Air Quality in 12 Cities",
                                      "blog/how-climate-resilient-farming-secures-our-future.html"),
    "co2-and-temperature-correlation": ("CO₂ and Temperature: Why One Correlation Isn't Enough",
                                        "blog/sustainable-irrigation-cost-effective-eco-friendly.html"),
    "finding-unusual-readings": ("Finding Unusual Readings in Climate Data",
                                 "blog/the-role-of-agronomists-in-modern-farming.html"),
}

# Simple pages: url name -> (title, old file)
PAGES = {
    "home": ("EarthScape", "index.html"),
    "about": ("About", "about.html"),
    "services": ("Service", "service.html"),
    "pricing": ("Access", "pricing.html"),
    "blog": ("Blogs", "blogs.html"),
    "contact": ("Contact", "contact.html"),
    "privacy": ("Privacy", "privacy-policy.html"),
    "changelog": ("Changelogs", "utilities/changelog.html"),
    "licenses": ("Licenses", "utilities/licenses.html"),
    "style_guide": ("Style Guides", "utilities/style-guides.html"),
    "not_found": ("Not Found", "404.html"),
}


def old_paths():
    """Old file to new URL."""
    from django.urls import reverse
    mapping = {old: reverse("website:" + name) for name, (_title, old) in PAGES.items() if name != "not_found"}
    mapping.update({old: reverse("website:service", args=[slug]) for slug, (_title, old) in SERVICES.items()})
    mapping.update({old: reverse("website:plan", args=[slug]) for slug, (_title, old) in PLANS.items()})
    mapping.update({old: reverse("website:post", args=[slug]) for slug, (_title, old) in POSTS.items()})
    mapping.update({"dashboard.html": "/dashboard/", "login.html": "/login/", "signup.html": "/signup/"})
    return mapping
