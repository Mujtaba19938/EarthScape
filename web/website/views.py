"""Public website: page views, the contact form and the newsletter sign-up."""
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from pymongo.errors import DuplicateKeyError

from accounts.auth import EMAIL_PATTERN, _count, _over_limit
from earthscape.crypto import email_fields, encrypt
from earthscape.db import db, notify, now
from earthscape.middleware import client_address

from .pages import PLANS, POSTS, SERVICES, old_paths, plan_cards

MAX_MESSAGES_PER_HOUR = 5


#----------------------------simple pages--------------------------------------

def index(request):
    return render(request, "website/index.html", {"page": "home"})


def about(request):
    return render(request, "website/about.html", {"page": "about"})


def services(request):
    return render(request, "website/services.html", {"page": "services"})


def pricing(request):
    context = {"page": "pricing", "plans": plan_cards()}
    return render(request, "website/pricing.html", context)


def blog(request):
    return render(request, "website/blog.html", {"page": "blog"})


def privacy(request):
    return render(request, "website/privacy.html", {"page": "privacy"})


def changelog(request):
    return render(request, "website/changelog.html", {"page": "changelog"})


def licenses(request):
    return render(request, "website/licenses.html", {"page": "licenses"})


def style_guide(request):
    return render(request, "website/style_guide.html", {"page": "style_guide"})


#----------------------------detail pages--------------------------------------

def service_detail(request, slug):
    if slug not in SERVICES:
        raise Http404("Page not found.")
    context = {"page": "services", "slug": slug}
    return render(request, "website/services/%s.html" % slug, context)


def plan_detail(request, slug):
    if slug not in PLANS:
        raise Http404("Page not found.")
    context = {"page": "pricing", "slug": slug}
    return render(request, "website/pricing/%s.html" % slug, context)


def post_detail(request, slug):
    if slug not in POSTS:
        raise Http404("Page not found.")
    context = {"page": "blog", "slug": slug}
    return render(request, "website/blog/%s.html" % slug, context)


#----------------------------forms--------------------------------------

def limited(request, kind):
    """Five an hour each."""
    key = "%s:%s" % (kind, client_address(request))
    if _over_limit(key, MAX_MESSAGES_PER_HOUR):
        return True
    _count(key, 60)
    return False


def contact(request):
    if request.method == "POST":
        form_data = request.POST
        errors = []

        name = form_data.get("name", "").strip()
        email = form_data.get("email", "").strip().lower()
        subject = form_data.get("subject", "").strip()
        message = form_data.get("message", "").strip()

        # Required fields
        if not name or not message:
            errors.append("Please enter your name and a message.")
        if not EMAIL_PATTERN.match(email):
            errors.append("Please enter a valid email address.")
        if len(name) > 100 or len(email) > 254 or len(subject) > 200 or len(message) > 4000:
            errors.append("One of the fields is too long.")
        # Flood limit
        if not errors and limited(request, "contact"):
            errors.append("Too many messages from here. Please try again later.")

        if errors:
            context = {"page": "contact", "form_errors": errors, "form_data": form_data}
            return render(request, "website/contact.html", context)

        # Stored encrypted
        db.contact_messages.insert_one({
            "name": name, "email_enc": encrypt(email), "subject": subject,
            "message_enc": encrypt(message), "created_at": now(),
        })
        for admin in db.users.find({"role": "Admin", "active": True}, {"_id": 1}):
            notify("New message from %s through the contact form." % name, str(admin["_id"]))

        messages.success(request, "Thank you! Your message has been received.")
        return redirect("website:contact")

    return render(request, "website/contact.html", {"page": "contact"})


@require_POST
def newsletter(request):
    email = request.POST.get("email", "").strip().lower()[:254]
    back = request.POST.get("next") or "/"
    if not back.startswith("/"):
        back = "/"

    if not EMAIL_PATTERN.match(email):
        messages.error(request, "Enter a valid email address.")
    elif limited(request, "newsletter"):
        messages.error(request, "Too many sign-ups from here. Please try again later.")
    else:
        try:
            db.newsletter.insert_one(dict(email_fields(email), created_at=now()))
        except DuplicateKeyError:
            # Same answer for repeats
            pass
        messages.success(request, "Thanks for subscribing.")
    return redirect(back + "#footer")


#----------------------------errors--------------------------------------

def not_found(request, exception=None):
    return render(request, "website/not_found.html", {"page": "not_found"}, status=404)


def old_page(request, path):
    """Old .html links."""
    target = old_paths().get(path)
    if not target:
        raise Http404("Page not found.")
    return redirect(target, permanent=True)
