'''permissions.py

Custom DRF permission classes that map to the two Django groups created in the
migration ``0003_create_groups.py``.
''' 

from rest_framework import permissions
from django.contrib.auth.models import Group


def _in_group(user, group_name: str) -> bool:
    return user.is_authenticated and user.groups.filter(name=group_name).exists()


class IsEstateAdmin(permissions.BasePermission):
    """Allow full access for users in the ``estate_admin`` group.
    """

    def has_permission(self, request, view):
        return _in_group(request.user, "estate_admin")


class IsHallAssistant(permissions.BasePermission):
    """Allow limited access for ``hall_assistant`` members.
    The assistant can manage beds and allocations but cannot modify
    top‑level entities such as buildings or amenity definitions.
    """

    def has_permission(self, request, view):
        # Hall assistants have permission for safe‑method actions on allowed models
        if not _in_group(request.user, "hall_assistant"):
            return False
        # Restrict to specific viewsets (Bed, Allocation, AmenityValue) – the view
        # will expose the ``allowed_actions`` attribute for fine‑grained checks.
        allowed_actions = getattr(view, "allowed_actions", None)
        if allowed_actions is None:
            # If the view does not declare allowed_actions, deny by default.
            return False
        if request.method in permissions.SAFE_METHODS:
            return "list" in allowed_actions or "retrieve" in allowed_actions
        # For mutable methods, only allow if the view explicitly permits it.
        return request.method in allowed_actions
