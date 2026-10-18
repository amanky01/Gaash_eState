"""
Django admin for the estate app.

NOTE: admin writes bypass services.py. That means no bed auto-generation and no
Unit/Bed status sync when editing here. Use it for staff-only inspection and
data repair; day-to-day writes go through the API.
"""
from django.contrib import admin

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


class CreatedByMixin:
    """Fills `created_by` with the current user for new objects (main form and inlines)."""

    def save_model(self, request, obj, form, change):
        if hasattr(obj, 'created_by_id') and obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for inst in instances:
            if hasattr(inst, 'created_by_id') and inst.created_by_id is None:
                inst.created_by = request.user
            inst.save()
        formset.save_m2m()


# ---------- Inlines ----------

class BlockInline(admin.TabularInline):
    model = Block
    extra = 0
    exclude = ('created_by',)
    show_change_link = True


class UnitInline(admin.TabularInline):
    model = Unit
    extra = 0
    exclude = ('created_by', 'area_sqft', 'monthly_rent')
    show_change_link = True


class BedInline(admin.TabularInline):
    model = Bed
    extra = 0


class BuildingAmenityInline(admin.TabularInline):
    model = AmenityValue
    fk_name = 'building'
    extra = 0
    exclude = ('block', 'unit')


class BlockAmenityInline(admin.TabularInline):
    model = AmenityValue
    fk_name = 'block'
    extra = 0
    exclude = ('building', 'unit')


class UnitAmenityInline(admin.TabularInline):
    model = AmenityValue
    fk_name = 'unit'
    extra = 0
    exclude = ('building', 'block')


# ---------- Model admins ----------

@admin.register(Building)
class BuildingAdmin(CreatedByMixin, admin.ModelAdmin):
    list_display = ('name', 'property_type', 'location', 'is_active', 'created_at')
    list_filter = ('property_type', 'is_active')
    search_fields = ('name', 'location')
    exclude = ('created_by',)
    inlines = [BlockInline, UnitInline, BuildingAmenityInline]


@admin.register(Block)
class BlockAdmin(CreatedByMixin, admin.ModelAdmin):
    list_display = ('name', 'building', 'is_active')
    list_filter = ('building__property_type', 'is_active')
    search_fields = ('name', 'building__name')
    exclude = ('created_by',)
    inlines = [BlockAmenityInline]


@admin.register(Unit)
class UnitAdmin(CreatedByMixin, admin.ModelAdmin):
    list_display = ('number', 'building', 'block', 'capacity', 'status', 'is_active')
    list_filter = ('building__property_type', 'status', 'is_active', 'building')
    search_fields = ('number', 'building__name', 'block__name')
    exclude = ('created_by',)
    inlines = [BedInline, UnitAmenityInline]


@admin.register(Bed)
class BedAdmin(admin.ModelAdmin):
    list_display = ('bed_number', 'unit', 'status', 'is_active')
    list_filter = ('status', 'is_active', 'unit__building')
    search_fields = ('bed_number', 'unit__number', 'unit__building__name')


@admin.register(Occupant)
class OccupantAdmin(CreatedByMixin, admin.ModelAdmin):
    list_display = ('full_name', 'occupant_type', 'gender', 'contact_number', 'is_active')
    list_filter = ('occupant_type', 'gender', 'is_active')
    search_fields = ('full_name', 'contact_number', 'email', 'external_ref_id')
    exclude = ('created_by',)


@admin.register(Allocation)
class AllocationAdmin(admin.ModelAdmin):
    list_display = ('occupant', 'unit', 'bed', 'status', 'start_date', 'end_date')
    list_filter = ('status', 'unit__building__property_type', 'unit__building')
    search_fields = ('occupant__full_name', 'unit__number', 'unit__building__name')
    date_hierarchy = 'start_date'
    exclude = ('allocated_by',)

    def save_model(self, request, obj, form, change):
        if obj.allocated_by_id is None:
            obj.allocated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(AmenityDefinition)
class AmenityDefinitionAdmin(CreatedByMixin, admin.ModelAdmin):
    list_display = ('name', 'level', 'value_type', 'is_active')
    list_filter = ('level', 'value_type', 'is_active')
    search_fields = ('name',)
    exclude = ('created_by',)

    def get_readonly_fields(self, request, obj=None):
        # Lock rule: level/value_type can't change once values exist.
        if obj is not None and obj.has_values():
            return ('level', 'value_type')
        return ()


@admin.register(AmenityValue)
class AmenityValueAdmin(admin.ModelAdmin):
    list_display = ('definition', 'building', 'block', 'unit', 'value_boolean', 'value_number', 'value_text')
    list_filter = ('definition__level', 'definition')