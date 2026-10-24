'''serializers.py

DRF serializers for the estate app.  They expose the models defined in
``backend/estate/models.py`` and are used by the viewsets below.
''' 

from rest_framework import serializers

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

class BuildingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Building
        fields = ["id", "name", "property_type", "location", "is_active", "created_at", "updated_at", "created_by"]
        read_only_fields = ["id", "created_at", "updated_at", "created_by"]

class BlockSerializer(serializers.ModelSerializer):
    class Meta:
        model = Block
        fields = ["id", "building", "name", "is_active", "created_at", "updated_at", "created_by"]
        read_only_fields = ["id", "created_at", "updated_at", "created_by"]

class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = [
            "id",
            "building",
            "block",
            "number",
            "capacity",
            "status",
            "floor",
            "area_sqft",
            "monthly_rent",
            "is_active",
            "created_at",
            "updated_at",
            "created_by",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "created_by"]

class BedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bed
        fields = ["id", "unit", "bed_number", "status", "is_active", "created_at", "updated_at", "created_by"]
        read_only_fields = ["id", "created_at", "updated_at", "created_by"]

class OccupantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Occupant
        fields = [
            "id",
            "occupant_type",
            "full_name",
            "gender",
            "contact_number",
            "email",
            "external_ref_id",
            "is_active",
            "created_at",
            "updated_at",
            "created_by",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "created_by"]

class AllocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Allocation
        fields = [
            "id",
            "occupant",
            "unit",
            "bed",
            "allocated_by",
            "start_date",
            "end_date",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

class AmenityDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AmenityDefinition
        fields = [
            "id",
            "name",
            "level",
            "value_type",
            "applicable_property_types",
            "is_active",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "created_by"]

class AmenityValueSerializer(serializers.ModelSerializer):
    class Meta:
        model = AmenityValue
        fields = [
            "id",
            "definition",
            "building",
            "block",
            "unit",
            "value_boolean",
            "value_number",
            "value_text",
            "is_active",
            "created_at",
            "updated_at",
            "created_by",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "created_by"]
