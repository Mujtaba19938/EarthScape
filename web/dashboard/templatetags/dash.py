"""Small display filters for dashboard templates."""
import datetime

from django import template

register = template.Library()


@register.filter
def when(value):
    """Readable UTC time."""
    if isinstance(value, (int, float)):
        value = datetime.datetime.fromtimestamp(value / 1000, datetime.timezone.utc)
    if not isinstance(value, datetime.datetime):
        return value or ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


@register.filter
def signed(value, suffix=""):
    """Adds plus sign."""
    if value is None:
        return "n/a"
    return ("+" if value > 0 else "") + str(value) + suffix


@register.filter
def number(value):
    """Thousands separators."""
    if value is None:
        return "n/a"
    try:
        return "{:,}".format(value)
    except (TypeError, ValueError):
        return value


@register.filter
def unit(value, text):
    """Value with unit."""
    return "n/a" if value is None else "%s %s" % (value, text)
