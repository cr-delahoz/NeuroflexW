from functools import wraps

from django.http import HttpResponseForbidden


def specialist_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if getattr(request.user, "role", None) != "SPECIALIST":
            return HttpResponseForbidden("Esta función es exclusiva de especialistas.")
        return view_func(request, *args, **kwargs)

    return wrapper
