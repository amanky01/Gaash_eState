"""serializers.py

Rules of thumb
* ``created_by`` / ``allocated_by`` / ``is_active`` / ``status`` are read-only: the server sets them.
* Structural writes (units, beds, allocations, amenity values, nested building)
  are executed by ``services.py``; serializers only validate and shape data.
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .constants import (
    AllocationStatus,
    AmenityValueType,
    OccupantType,
    PropertyType,
)
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

# "Room No" vs "Shop No" is a display label resolved from the building type.
UNIT_LABELS = {
    PropertyType.HOSTEL_BOYS: 'Room No',
    PropertyType.HOSTEL_GIRLS: 'Room No',
    PropertyType.SHOP_COMPLEX: 'Shop No',
    PropertyType.TEACHER_QUARTERS: 'Quarter No',
}


def to_drf_error(exc: DjangoValidationError) -> serializers.ValidationError:
    detail = exc.message_dict if hasattr(exc, 'error_dict') else exc.messages
    return serializers.ValidationError(detail)


def amenity_value_of(av: AmenityValue):
    vt = av.definition.value_type
    if vt == AmenityValueType.BOOLEAN:
        return av.value_boolean
    if vt == AmenityValueType.NUMBER:
        return None if av.value_number is None else float(av.value_number)
    return av.value_text


# ---------------------------------------------------------------------------
# Amenities
# ---------------------------------------------------------------------------

class AmenityValueBriefSerializer(serializers.ModelSerializer):
    """Compact form embedded in Building/Block/Unit responses."""
    name = serializers.CharField(source='definition.name', read_only=True)
    value_type = serializers.CharField(source='definition.value_type', read_only=True)
    value = serializers.SerializerMethodField()

    class Meta:
        model = AmenityValue
        fields = ['id', 'definition', 'name', 'value_type', 'value']

    def get_value(self, obj):
        return amenity_value_of(obj)


class AmenityDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AmenityDefinition
        fields = [
            'id', 'name', 'level', 'value_type', 'applicable_property_types',
            'is_active', 'created_by', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'is_active', 'created_by', 'created_at', 'updated_at']

    def validate_applicable_property_types(self, value):
        valid = set(PropertyType.values)
        if not isinstance(value, list) or any(p not in valid for p in value):
            raise serializers.ValidationError(f"Must be a list of: {', '.join(sorted(valid))}.")
        return value

    def validate(self, attrs):
        inst = self.instance
        # Lock rule: level / value_type cannot change once values exist.
        if inst is not None and inst.has_values():
            for f in ('level', 'value_type'):
                if f in attrs and attrs[f] != getattr(inst, f):
                    raise serializers.ValidationError(
                        {f: "Cannot be changed once values exist. Create a new definition instead."}
                    )
        return attrs


class AmenityValueSerializer(serializers.ModelSerializer):
    definition_name = serializers.CharField(source='definition.name', read_only=True)
    level = serializers.CharField(source='definition.level', read_only=True)
    value_type = serializers.CharField(source='definition.value_type', read_only=True)
    value = serializers.SerializerMethodField()

    class Meta:
        model = AmenityValue
        fields = [
            'id', 'definition', 'definition_name', 'level', 'value_type',
            'building', 'block', 'unit',
            'value_boolean', 'value_number', 'value_text', 'value',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
        validators = []  # uniqueness is handled by the upsert in services.set_amenity_value

    def get_value(self, obj):
        return amenity_value_of(obj)

    def validate(self, attrs):
        inst = self.instance
        if inst is not None:
            for f in ('definition', 'building', 'block', 'unit'):
                if f in attrs and attrs[f] != getattr(inst, f):
                    raise serializers.ValidationError({f: "Cannot be changed. Delete and re-create instead."})
        fields = ['definition', 'building', 'block', 'unit', 'value_boolean', 'value_number', 'value_text']
        data = {}
        for f in fields:
            if f in attrs:
                data[f] = attrs[f]
            elif inst is not None:
                data[f] = getattr(inst, f)
            else:
                data[f] = '' if f == 'value_text' else None
        try:
            AmenityValue(**data).clean()
        except DjangoValidationError as exc:
            raise to_drf_error(exc)
        return attrs


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

class _AmenitiesMixin(serializers.Serializer):
    amenities = serializers.SerializerMethodField()

    def get_amenities(self, obj):
        return AmenityValueBriefSerializer(obj.amenity_values.all(), many=True).data


class BuildingSerializer(_AmenitiesMixin, serializers.ModelSerializer):
    class Meta:
        model = Building
        fields = [
            'id', 'name', 'property_type', 'location', 'is_active', 'amenities',
            'created_by', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'is_active', 'created_by', 'created_at', 'updated_at']

    def validate(self, attrs):
        inst = self.instance
        if inst is not None and 'property_type' in attrs and attrs['property_type'] != inst.property_type:
            if inst.units.exists():
                raise serializers.ValidationError(
                    {'property_type': "Cannot change the type of a building that already has units."}
                )
        return attrs


class BlockSerializer(_AmenitiesMixin, serializers.ModelSerializer):
    class Meta:
        model = Block
        fields = ['id', 'building', 'name', 'is_active', 'amenities', 'created_by', 'created_at', 'updated_at']
        read_only_fields = ['id', 'is_active', 'created_by', 'created_at', 'updated_at']

    def validate(self, attrs):
        if self.instance is not None and 'building' in attrs and attrs['building'] != self.instance.building:
            raise serializers.ValidationError({'building': "A block cannot move to another building."})
        return attrs


def _active_allocations(bed):
    cached = getattr(bed, 'active_allocations', None)
    if cached is not None:
        return cached
    return list(bed.allocations.filter(status=AllocationStatus.ACTIVE).select_related('occupant'))


def _occupant_brief(bed):
    allocs = _active_allocations(bed)
    if not allocs:
        return None
    o = allocs[0].occupant
    return {'id': o.id, 'full_name': o.full_name}


class BedSerializer(serializers.ModelSerializer):
    occupant = serializers.SerializerMethodField()

    class Meta:
        model = Bed
        fields = ['id', 'unit', 'bed_number', 'status', 'is_active', 'occupant', 'created_at', 'updated_at']
        read_only_fields = ['id', 'status', 'is_active', 'created_at', 'updated_at']
        extra_kwargs = {'bed_number': {'required': False}}
        validators = []  # uniqueness is enforced in services (soft-deleted beds keep their number)

    def get_occupant(self, obj):
        return _occupant_brief(obj)

    def validate(self, attrs):
        if self.instance is not None and 'unit' in attrs and attrs['unit'] != self.instance.unit:
            raise serializers.ValidationError({'unit': "A bed cannot move to another unit."})
        return attrs


class UnitSerializer(_AmenitiesMixin, serializers.ModelSerializer):
    number_label = serializers.SerializerMethodField()
    beds = serializers.SerializerMethodField()

    class Meta:
        model = Unit
        fields = [
            'id', 'building', 'block', 'number', 'number_label', 'capacity', 'status',
            'floor', 'area_sqft', 'monthly_rent', 'is_active', 'beds', 'amenities',
            'created_by', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'status', 'is_active', 'created_by', 'created_at', 'updated_at']

    def get_number_label(self, obj):
        return UNIT_LABELS.get(obj.building.property_type, 'Unit No')

    def get_beds(self, obj):
        from .services import _bed_key
        beds = sorted((b for b in obj.beds.all() if b.is_active), key=_bed_key)
        return [
            {'id': b.id, 'bed_number': b.bed_number, 'status': b.status, 'occupant': _occupant_brief(b)}
            for b in beds
        ]

    def validate(self, attrs):
        inst = self.instance
        if inst is not None and 'building' in attrs and attrs['building'] != inst.building:
            raise serializers.ValidationError({'building': "A unit cannot move to another building."})
        building = attrs.get('building') or (inst.building if inst else None)
        block = attrs.get('block', inst.block if inst else None)
        if block is not None and building is not None and block.building_id != building.id:
            raise serializers.ValidationError({'block': "Block must belong to the unit's building."})
        return attrs


class BulkUnitSerializer(serializers.Serializer):
    building = serializers.PrimaryKeyRelatedField(queryset=Building.objects.filter(is_active=True))
    block = serializers.PrimaryKeyRelatedField(queryset=Block.objects.filter(is_active=True), required=False, allow_null=True)
    start = serializers.IntegerField(min_value=0)
    end = serializers.IntegerField(min_value=0)
    prefix = serializers.CharField(required=False, allow_blank=True, default='', max_length=20)
    capacity = serializers.IntegerField(min_value=1, default=1)
    floor = serializers.CharField(required=False, allow_blank=True, default='', max_length=20)
    area_sqft = serializers.DecimalField(max_digits=8, decimal_places=2, required=False, allow_null=True)
    monthly_rent = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)

    def validate(self, attrs):
        block = attrs.get('block')
        if block is not None and block.building_id != attrs['building'].id:
            raise serializers.ValidationError({'block': "Block must belong to the building."})
        return attrs


# ---- nested "create building" wizard payload -------------------------------

class AmenityInputSerializer(serializers.Serializer):
    definition = serializers.PrimaryKeyRelatedField(queryset=AmenityDefinition.objects.filter(is_active=True))
    value = serializers.JSONField()  # coerced/validated against the definition's type in services


class UnitInputSerializer(serializers.Serializer):
    number = serializers.CharField(max_length=50)
    capacity = serializers.IntegerField(min_value=1, default=1)
    floor = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')
    area_sqft = serializers.DecimalField(max_digits=8, decimal_places=2, required=False, allow_null=True, default=None)
    monthly_rent = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True, default=None)
    amenities = AmenityInputSerializer(many=True, required=False)


class BlockInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    amenities = AmenityInputSerializer(many=True, required=False)
    units = UnitInputSerializer(many=True, required=False)


class BuildingCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    property_type = serializers.ChoiceField(choices=PropertyType.choices)
    location = serializers.CharField(required=False, allow_blank=True, default='')
    amenities = AmenityInputSerializer(many=True, required=False)
    blocks = BlockInputSerializer(many=True, required=False)
    units = UnitInputSerializer(many=True, required=False)

    def validate(self, attrs):
        names = [b['name'].strip().lower() for b in attrs.get('blocks', [])]
        if len(names) != len(set(names)):
            raise serializers.ValidationError({'blocks': "Block names must be unique within a building."})
        numbers = [u['number'].strip().lower() for u in attrs.get('units', [])]
        for b in attrs.get('blocks', []):
            numbers += [u['number'].strip().lower() for u in b.get('units', [])]
        if len(numbers) != len(set(numbers)):
            raise serializers.ValidationError("Unit numbers must be unique within a building.")
        return attrs


# ---------------------------------------------------------------------------
# People & allocations
# ---------------------------------------------------------------------------

class OccupantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Occupant
        fields = [
            'id', 'occupant_type', 'full_name', 'gender', 'contact_number', 'email',
            'external_ref_id', 'is_active', 'created_by', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'is_active', 'created_by', 'created_at', 'updated_at']

    def validate(self, attrs):
        inst = self.instance
        otype = attrs.get('occupant_type', inst.occupant_type if inst else None)
        gender = attrs.get('gender', inst.gender if inst else '')
        if otype == OccupantType.STUDENT and not gender:
            raise serializers.ValidationError({'gender': "Required for students (needed for boys/girls hostel rules)."})
        if inst is not None and (otype != inst.occupant_type or gender != inst.gender):
            if inst.allocations.filter(status=AllocationStatus.ACTIVE).exists():
                raise serializers.ValidationError("Cannot change type/gender while the occupant has an active allocation.")
        return attrs


class AllocationSerializer(serializers.ModelSerializer):
    occupant_name = serializers.CharField(source='occupant.full_name', read_only=True)
    building = serializers.IntegerField(source='unit.building_id', read_only=True)
    building_name = serializers.CharField(source='unit.building.name', read_only=True)
    unit_number = serializers.CharField(source='unit.number', read_only=True)
    bed_number = serializers.SerializerMethodField()

    class Meta:
        model = Allocation
        fields = [
            'id', 'occupant', 'occupant_name', 'building', 'building_name',
            'unit', 'unit_number', 'bed', 'bed_number',
            'allocated_by', 'start_date', 'end_date', 'status', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'allocated_by', 'status', 'created_at', 'updated_at']
        extra_kwargs = {'start_date': {'required': False}}  # defaults to today in services
        validators = []  # all allocation rules live in services.allocate_unit

    def get_bed_number(self, obj):
        return obj.bed.bed_number if obj.bed_id else None


class VacateSerializer(serializers.Serializer):
    end_date = serializers.DateField(required=False)
