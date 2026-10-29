import os

from django import template
from django.conf import settings
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def static_versioned(path):
    """Like {% static %}, but appends the file's mtime as a cache-busting query param.

    Browsers otherwise cache static JS/CSS indefinitely, so an edit doesn't
    take effect for a returning visitor until a hard refresh.
    """
    url = static(path)
    absolute_path = settings.BASE_DIR / "static" / path
    try:
        version = int(os.path.getmtime(absolute_path))
    except OSError:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}v={version}"
