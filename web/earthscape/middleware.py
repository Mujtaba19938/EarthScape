"""Small request helpers shared by every app."""
from . import config


def instance_header(get_response):
    """Names the instance."""
    def middleware(request):
        response = get_response(request)
        response["X-EarthScape-Instance"] = config.INSTANCE_NAME
        return response
    return middleware


def client_address(request):
    """Real visitor address."""
    address = request.META.get("REMOTE_ADDR", "unknown")
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    # Only Apache on this machine may say who the visitor is.
    if forwarded and address in ("127.0.0.1", "::1"):
        return forwarded.split(",")[-1].strip()
    return address
