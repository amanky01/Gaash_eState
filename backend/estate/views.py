'''views.py

DRF viewsets and custom endpoints for the estate application.
They use the serializers defined in ``serializers.py`` and the
permission classes from ``permissions.py``.
'''

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404

from rest_framework import viewsets, generics, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action

from .models import (
    Building,
    Block,
    Unit,
    Bed,
    Occupant,
    Allocation,
    AmenityDefinition,
    AmenityValue,
)
from .serializers import (
    BuildingSerializer,
    BlockSerializer,
    UnitSerializer,
    BedSerializer,
    OccupantSerializer,
    AllocationSerializer,
    AmenityDefinitionSerializer,
    AmenityValueSerializer,
)
from .permissions import IsEstateAdmin, IsHallAssistant

# Helper mixin to declare allowed actions for the HallAssistant permission
class AllowedActionsMixin:
    """Mixin that sets ``allowed_actions`` for HallAssistant permission checks.
    Sub‑classes should override ``allowed_actions`` with a set of HTTP method strings
    that the ``hall_assistant`` group is permitted to use.
    """
    allowed_actions = set()

    def get_permissions(self):
        # Authenticated users are required for all endpoints.
        if not permissions.IsAuthenticated().has_permission(self.request, self):
            return [permissions.IsAuthenticated()]
        # Estate admin gets full access.
        if IsEstateAdmin().has_permission(self.request, self):
            return [IsEstateAdmin()]
        # Hall assistant gets limited access based on allowed_actions.
        if IsHallAssistant().has_permission(self.request, self):
            return [IsHallAssistant()]
        # Default fallback – require authentication.
        return [permissions.IsAuthenticated()]

# ---------------------------------------------------------------------------
# Model viewsets
# ---------------------------------------------------------------------------

class BuildingViewSet(AllowedActionsMixin, viewsets.ModelViewSet):
    queryset = Building.objects.all()
    serializer_class = BuildingSerializer
    # No assistant access – keep allowed_actions empty.
    allowed_actions = set()

class BlockViewSet(AllowedActionsMixin, viewsets.ModelViewSet):
    queryset = Block.objects.select_related('building').all()
    serializer_class = BlockSerializer
    allowed_actions = set()

class UnitViewSet(AllowedActionsMixin, viewsets.ModelViewSet):
    queryset = Unit.objects.select_related('building', 'block').all()
    serializer_class = UnitSerializer
    allowed_actions = set()

class BedViewSet(AllowedActionsMixin, viewsets.ModelViewSet):
    queryset = Bed.objects.select_related('unit').all()
    serializer_class = BedSerializer
    # Hall assistants can manage beds fully.
    allowed_actions = {"GET", "POST", "PUT", "PATCH", "DELETE"}

class OccupantViewSet(AllowedActionsMixin, viewsets.ModelViewSet):
    queryset = Occupant.objects.all()
    serializer_class = OccupantSerializer
    allowed_actions = set()

class AllocationViewSet(AllowedActionsMixin, viewsets.ModelViewSet):
    queryset = Allocation.objects.select_related('occupant', 'unit', 'bed').all()
    serializer_class = AllocationSerializer
    # Hall assistants can manage allocations.
    allowed_actions = {"GET", "POST", "PUT", "PATCH", "DELETE"}

    @action(detail=True, methods=["post"], url_path="vacate")
    def vacate(self, request, pk=None):
        """Custom endpoint to vacate an allocation using the service layer.
        Calls ``vacate_allocation`` to encapsulate business logic.
        """
        from .services import vacate_allocation
        allocation = self.get_object()
        vacated = vacate_allocation(allocation.id, vacated_by=request.user)
        return Response(self.get_serializer(vacated).data)

class AmenityDefinitionViewSet(AllowedActionsMixin, viewsets.ModelViewSet):
    queryset = AmenityDefinition.objects.all()
    serializer_class = AmenityDefinitionSerializer
    allowed_actions = set()

class AmenityValueViewSet(AllowedActionsMixin, viewsets.ModelViewSet):
    queryset = AmenityValue.objects.select_related('definition').all()
    serializer_class = AmenityValueSerializer
    # Hall assistants can manage values.
    allowed_actions = {"GET", "POST", "PUT", "PATCH", "DELETE"}

# ---------------------------------------------------------------------------
# Custom API endpoints
# ---------------------------------------------------------------------------

class StatsView(generics.GenericAPIView):
    """Endpoint providing simple estate statistics.
    URL: ``/api/stats/``
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        data = {
            "buildings": Building.objects.count(),
            "blocks": Block.objects.count(),
            "units": Unit.objects.count(),
            "occupied_units": Unit.objects.filter(status="OCCUPIED").count(),
            "vacant_units": Unit.objects.filter(status="VACANT").count(),
            "beds": Bed.objects.count(),
            "occupied_beds": Bed.objects.filter(status="OCCUPIED").count(),
            "amenity_definitions": AmenityDefinition.objects.count(),
            "amenity_values": AmenityValue.objects.count(),
        }
        return Response(data)

class StudentRoomView(generics.RetrieveAPIView):
    """Return the active allocation (room/bed) for a given occupant.
    URL pattern: ``/api/occupants/<pk>/room/``
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AllocationSerializer

    def get_object(self):
        occupant = get_object_or_404(Occupant, pk=self.kwargs["pk"])
        allocation = (
            Allocation.objects.filter(occupant=occupant, status="ACTIVE")
            .order_by("-start_date")
            .first()
        )
        if not allocation:
            raise generics.Http404("No active allocation for this occupant.")
        return allocation

# End of views.py
