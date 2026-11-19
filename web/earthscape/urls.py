"""Top-level URLs."""
import mimetypes

from django.contrib.staticfiles import finders
from django.http import FileResponse, Http404
from django.urls import include, path, re_path

from dashboard.views import health


def static_file(request, path):
    """Serves app static files."""
    # Waitress has no static server, so Django serves them from each app.
    found = finders.find(path)
    if not found or ".." in path:
        raise Http404("Not found.")
    content_type = mimetypes.guess_type(found)[0] or "application/octet-stream"
    response = FileResponse(open(found, "rb"), content_type=content_type)
    response["Cache-Control"] = "public, max-age=3600"
    return response


urlpatterns = [
    path("api/health", health, name="health"),
    re_path(r"^static/(?P<path>.+)$", static_file),
    path("dashboard/", include("dashboard.urls")),
    path("", include("accounts.urls")),
    path("", include("website.urls")),
]

handler404 = "website.views.not_found"
