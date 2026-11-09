"""views.py

Thin HTTP layer: validate with serializers, delegate writes to ``services.py``.

Roles (see permissions.py)
* estate_admin   : everything.
* hall_assistant : only the actions in each view's ``assistant_actions``.

List endpoints: ``?is_active=true`` (default) | ``false`` | ``all`` plus per-view filters and ``?search=``.
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.db.models import Count, Prefetch, Q
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .constants import AllocationStatus, AmenityValueType
from .models import (
    Allocation,
    AmenityDefinition,
    AmenityValue,
    Bed,
    Block,
    Building,
    Occupant,
    Unit,
)
from .permissions import IsEstateAdmin, IsEstateStaff, IsHallAssistant
from .serializers import (
    AllocationSerializer,
    AmenityDefinitionSerializer,
    AmenityValueSerializer,
    BedSerializer,
    BlockSerializer,
    BuildingCreateSerializer,
    BuildingSerializer,
    BulkUnitSerializer,
    OccupantSerializer,
    UnitSerializer,
    VacateSerializer,
    to_drf_error,
)

ACTIVE = AllocationStatus.ACTIVE

_active_allocs = Prefetch(
    'allocations',
    queryset=Allocation.objects.filter(status=ACTIVE).select_related('occupant'),
    to_attr='active_allocations',
)
_beds_with_occupant = Prefetch('beds', queryset=Bed.objects.prefetch_related(_active_allocs))


# ---------------------------------------------------------------------------
# Shared behaviour
# ---------------------------------------------------------------------------

class EstateViewMixin:
    """Permissions, error mapping, list filtering."""
    permission_classes = [IsEstateAdmin | IsHallAssistant]
    assistant_actions = frozenset()   # DRF action names a hall_assistant may call
    filter_fields = {}                # ?param=value  ->  ORM lookup
    search_fields = ()                # ?search=text  ->  icontains on these

    def handle_exception(self, exc):
        if isinstance(exc, DjangoValidationError):
            exc = to_drf_error(exc)
        elif isinstance(exc, IntegrityError):
            exc = serializers.ValidationError("Conflicts with existing data (duplicate or constraint violation).")
        return super().handle_exception(exc)

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action != 'list':
            return qs
        params = self.request.query_params
        flag = params.get('is_active', 'true').lower()
        if flag != 'all' and any(f.name == 'is_active' for f in qs.model._meta.get_fields()):
            qs = qs.filter(is_active=(flag == 'true'))
        try:
            for param, lookup in self.filter_fields.items():
                val = params.get(param)
                if val not in (None, ''):
                    qs = qs.filter(**{lookup: val})
        except (ValueError, TypeError, DjangoValidationError):
            raise serializers.ValidationError("Invalid filter value.")
        term = params.get('search', '').strip()
        if term and self.search_fields:
            cond = Q()
            for f in self.search_fields:
                cond |= Q(**{f'{f}__icontains': term})
            qs = qs.filter(cond)
        return qs

    def refetch(self, obj):
        return self.get_queryset().get(pk=obj.pk)


class SoftDeleteMixin:
    """DELETE deactivates (never hard-deletes); POST .../activate/ restores. Admin only."""

    def destroy(self, request, *args, **kwargs):
        services.deactivate(self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        obj = services.activate(self.get_object())
        return Response(self.get_serializer(obj).data)


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

class BuildingViewSet(EstateViewMixin, SoftDeleteMixin, viewsets.ModelViewSet):
    queryset = Building.objects.prefetch_related('amenity_values__definition')
    serializer_class = BuildingSerializer
    assistant_actions = frozenset({'list', 'retrieve'})
    filter_fields = {'property_type': 'property_type'}
    search_fields = ('name', 'location')

    def create(self, request, *args, **kwargs):
        """Wizard payload: building + amenities + blocks + units (+ auto beds) in one transaction."""
        ser = BuildingCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        building = services.create_building_with_structure(created_by=request.user, **ser.validated_data)
        return Response(self.get_serializer(self.refetch(building)).data, status=status.HTTP_201_CREATED)


class BlockViewSet(EstateViewMixin, SoftDeleteMixin, viewsets.ModelViewSet):
    queryset = Block.objects.select_related('building').prefetch_related('amenity_values__definition')
    serializer_class = BlockSerializer
    assistant_actions = frozenset({'list', 'retrieve'})
    filter_fields = {'building': 'building_id'}
    search_fields = ('name',)

    def perform_create(self, serializer):
        block = Block(created_by=self.request.user, **serializer.validated_data)
        block.full_clean()
        block.save()
        serializer.instance = block


class UnitViewSet(EstateViewMixin, SoftDeleteMixin, viewsets.ModelViewSet):
    queryset = (
        Unit.objects.select_related('building', 'block')
        .prefetch_related(_beds_with_occupant, 'amenity_values__definition')
    )
    serializer_class = UnitSerializer
    assistant_actions = frozenset({'list', 'retrieve'})
    filter_fields = {
        'building': 'building_id', 'block': 'block_id', 'status': 'status',
        'property_type': 'building__property_type', 'floor': 'floor',
    }
    search_fields = ('number',)

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        unit = services.create_unit(created_by=request.user, **ser.validated_data)
        return Response(self.get_serializer(self.refetch(unit)).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        unit = self.get_object()
        ser = self.get_serializer(unit, data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        unit = services.update_unit(unit, **ser.validated_data)
        return Response(self.get_serializer(self.refetch(unit)).data)

    @action(detail=False, methods=['post'])
    def bulk(self, request):
        """Bulk helper, e.g. {"building": 1, "start": 101, "end": 120, "capacity": 4}."""
        ser = BulkUnitSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        units = services.bulk_create_units(created_by=request.user, **ser.validated_data)
        qs = self.get_queryset().filter(pk__in=[u.pk for u in units])
        return Response(self.get_serializer(qs, many=True).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def maintenance(self, request, pk=None):
        """Body: {"maintenance": true|false}"""
        on = request.data.get('maintenance')
        if not isinstance(on, bool):
            raise serializers.ValidationError({'maintenance': "Send true or false."})
        unit = services.set_unit_maintenance(self.get_object(), on)
        return Response(self.get_serializer(self.refetch(unit)).data)


class BedViewSet(EstateViewMixin, viewsets.ModelViewSet):
    queryset = Bed.objects.select_related('unit', 'unit__building').prefetch_related(_active_allocs)
    serializer_class = BedSerializer
    assistant_actions = frozenset({'list', 'retrieve', 'create', 'update', 'partial_update', 'destroy', 'maintenance'})
    filter_fields = {'unit': 'unit_id', 'status': 'status', 'building': 'unit__building_id'}
    search_fields = ('bed_number',)

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        bed = services.add_bed(d['unit'], d.get('bed_number'))
        return Response(self.get_serializer(self.refetch(bed)).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        bed = self.get_object()
        ser = self.get_serializer(bed, data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        number = ser.validated_data.get('bed_number')
        if number is None:
            raise serializers.ValidationError({'bed_number': "This field is required."})
        bed = services.rename_bed(bed, number)
        return Response(self.get_serializer(self.refetch(bed)).data)

    def destroy(self, request, *args, **kwargs):
        services.remove_bed(self.get_object())  # soft delete, capacity -= 1
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def maintenance(self, request, pk=None):
        """Body: {"maintenance": true|false}"""
        on = request.data.get('maintenance')
        if not isinstance(on, bool):
            raise serializers.ValidationError({'maintenance': "Send true or false."})
        bed = services.set_bed_maintenance(self.get_object(), on)
        return Response(self.get_serializer(self.refetch(bed)).data)


# ---------------------------------------------------------------------------
# People & allocations
# ---------------------------------------------------------------------------

class OccupantViewSet(EstateViewMixin, SoftDeleteMixin, viewsets.ModelViewSet):
    queryset = Occupant.objects.all()
    serializer_class = OccupantSerializer
    assistant_actions = frozenset({'list', 'retrieve', 'create', 'update', 'partial_update', 'room'})
    filter_fields = {'occupant_type': 'occupant_type', 'gender': 'gender'}
    search_fields = ('full_name', 'contact_number', 'email', 'external_ref_id')

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['get'])
    def room(self, request, pk=None):
        """Where does this person live/work now? (shopkeepers can have several active allocations)"""
        occupant = self.get_object()
        allocs = (
            Allocation.objects.filter(occupant=occupant, status=ACTIVE)
            .select_related('occupant', 'unit', 'unit__building', 'bed')
            .order_by('-start_date')
        )
        return Response({
            'occupant': OccupantSerializer(occupant).data,
            'allocations': AllocationSerializer(allocs, many=True).data,
        })


class AllocationViewSet(
    EstateViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """No update/delete: history is permanent. Use ``vacate`` (move-out) or ``cancel`` (mistake)."""
    queryset = Allocation.objects.select_related('occupant', 'unit', 'unit__building', 'bed')
    serializer_class = AllocationSerializer
    assistant_actions = frozenset({'list', 'retrieve', 'create', 'vacate', 'cancel'})
    filter_fields = {
        'status': 'status', 'occupant': 'occupant_id', 'unit': 'unit_id',
        'bed': 'bed_id', 'building': 'unit__building_id',
    }
    search_fields = ('occupant__full_name', 'unit__number')

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        allocation = services.allocate_unit(allocated_by=request.user, **ser.validated_data)
        return Response(self.get_serializer(self.refetch(allocation)).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def vacate(self, request, pk=None):
        """Optional body: {"end_date": "YYYY-MM-DD"} (defaults to today)."""
        body = VacateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        allocation = services.vacate_allocation(self.get_object(), end_date=body.validated_data.get('end_date'))
        return Response(self.get_serializer(self.refetch(allocation)).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        allocation = services.cancel_allocation(self.get_object())
        return Response(self.get_serializer(self.refetch(allocation)).data)


# ---------------------------------------------------------------------------
# Amenities
# ---------------------------------------------------------------------------

class AmenityDefinitionViewSet(EstateViewMixin, SoftDeleteMixin, viewsets.ModelViewSet):
    queryset = AmenityDefinition.objects.all()
    serializer_class = AmenityDefinitionSerializer
    assistant_actions = frozenset({'list', 'retrieve'})
    filter_fields = {'level': 'level', 'value_type': 'value_type'}
    search_fields = ('name',)

    def perform_create(self, serializer):
        d = AmenityDefinition(created_by=self.request.user, **serializer.validated_data)
        d.full_clean()
        d.save()
        serializer.instance = d


def _value_from(definition, data):
    return {
        AmenityValueType.BOOLEAN: data.get('value_boolean'),
        AmenityValueType.NUMBER: data.get('value_number'),
        AmenityValueType.TEXT: data.get('value_text'),
    }[definition.value_type]


class AmenityValueViewSet(EstateViewMixin, viewsets.ModelViewSet):
    """POST is an upsert: posting a value for a target that already has one overwrites it."""
    queryset = AmenityValue.objects.select_related('definition')
    serializer_class = AmenityValueSerializer
    assistant_actions = frozenset({'list', 'retrieve', 'create', 'update', 'partial_update'})
    filter_fields = {
        'definition': 'definition_id', 'building': 'building_id', 'block': 'block_id', 'unit': 'unit_id',
    }

    def perform_create(self, serializer):
        d = serializer.validated_data
        serializer.instance = services.set_amenity_value(
            d['definition'], _value_from(d['definition'], d),
            building=d.get('building'), block=d.get('block'), unit=d.get('unit'),
        )

    def perform_update(self, serializer):
        inst = serializer.instance
        merged = {
            'value_boolean': inst.value_boolean, 'value_number': inst.value_number, 'value_text': inst.value_text,
            **serializer.validated_data,
        }
        serializer.instance = services.set_amenity_value(
            inst.definition, _value_from(inst.definition, merged),
            building=inst.building, block=inst.block, unit=inst.unit,
        )


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def _tally(qs, key):
    return {r[key]: r['n'] for r in qs.order_by().values(key).annotate(n=Count('id'))}


class StatsView(APIView):
    """GET /api/estate/stats/  - occupancy overview (active records only)."""
    permission_classes = [IsEstateStaff]

    def get(self, request):
        buildings = Building.objects.filter(is_active=True)
        units = Unit.objects.filter(is_active=True, building__is_active=True)
        beds = Bed.objects.filter(is_active=True, unit__is_active=True, unit__building__is_active=True)

        by_type = {}
        rows = units.order_by().values('building__property_type', 'status').annotate(n=Count('id'))
        for r in rows:
            t = by_type.setdefault(r['building__property_type'], {'total': 0, 'by_status': {}})
            t['by_status'][r['status']] = r['n']
            t['total'] += r['n']

        return Response({
            'buildings': buildings.count(),
            'blocks': Block.objects.filter(is_active=True, building__is_active=True).count(),
            'units': {'total': units.count(), 'by_status': _tally(units, 'status')},
            'beds': {'total': beds.count(), 'by_status': _tally(beds, 'status')},
            'occupants': {
                'total': Occupant.objects.filter(is_active=True).count(),
                'by_type': _tally(Occupant.objects.filter(is_active=True), 'occupant_type'),
            },
            'active_allocations': Allocation.objects.filter(status=ACTIVE).count(),
            'by_property_type': by_type,
        })
