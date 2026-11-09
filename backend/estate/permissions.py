"""permissions.py

Two roles, backed by the Django groups created in migration 0003:

* ``estate_admin``    - full access to everything in the estate API.
* ``hall_assistant``  - only the actions a view lists in ``assistant_actions``
                        (DRF action names such as ``list``, ``create``, ``vacate``).

Superusers are treated as estate admins. Anyone else (including logged-in users
with no group) is denied.

Usage on a view:  permission_classes = [IsEstateAdmin | IsHallAssistant]
"""
from rest_framework.permissions import BasePermission

ESTATE_ADMIN = 'estate_admin'
HALL_ASSISTANT = 'hall_assistant'


def _roles(request):
    """Group names of the requesting user, cached on the request (1 query max)."""
    user = request.user
    if not (user and user.is_authenticated):
        return frozenset()
    cached = getattr(request, '_estate_roles', None)
    if cached is None:
        cached = frozenset(
            user.groups.filter(name__in=[ESTATE_ADMIN, HALL_ASSISTANT]).values_list('name', flat=True)
        )
        request._estate_roles = cached
    return cached


def is_estate_admin(request):
    user = request.user
    return bool(user and user.is_authenticated and (user.is_superuser or ESTATE_ADMIN in _roles(request)))


def is_hall_assistant(request):
    return HALL_ASSISTANT in _roles(request)


class IsEstateAdmin(BasePermission):
    def has_permission(self, request, view):
        return is_estate_admin(request)


class IsHallAssistant(BasePermission):
    """Hall assistants may only perform the actions listed in ``view.assistant_actions``."""

    def has_permission(self, request, view):
        if not is_hall_assistant(request):
            return False
        return getattr(view, 'action', None) in getattr(view, 'assistant_actions', ())


class IsEstateStaff(BasePermission):
    """Any estate role. For plain APIViews (stats etc.) that have no per-action rules."""

    def has_permission(self, request, view):
        return is_estate_admin(request) or is_hall_assistant(request)
