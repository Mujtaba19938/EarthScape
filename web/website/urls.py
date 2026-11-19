"""Public website URLs."""
from django.urls import path, re_path

from . import views

app_name = "website"

urlpatterns = [
    path("", views.index, name="home"),
    path("about/", views.about, name="about"),
    path("services/", views.services, name="services"),
    path("services/<slug:slug>/", views.service_detail, name="service"),
    path("pricing/", views.pricing, name="pricing"),
    path("pricing/<slug:slug>/", views.plan_detail, name="plan"),
    path("blog/", views.blog, name="blog"),
    path("blog/<slug:slug>/", views.post_detail, name="post"),
    path("contact/", views.contact, name="contact"),
    path("newsletter/", views.newsletter, name="newsletter"),
    path("privacy-policy/", views.privacy, name="privacy"),
    path("changelog/", views.changelog, name="changelog"),
    path("licenses/", views.licenses, name="licenses"),
    path("style-guide/", views.style_guide, name="style_guide"),
    # Old Webflow file names
    re_path(r"^(?P<path>[a-z0-9/_-]+\.html)$", views.old_page),
]
