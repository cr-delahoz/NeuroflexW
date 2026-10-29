from updater.services import get_current_version


def dashboard_version(request):
    return {"dashboard_version": get_current_version()}
