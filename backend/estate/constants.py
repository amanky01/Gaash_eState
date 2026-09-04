from django.db import models

class PropertyType(models.TextChoices):
    HOSTEL_BOYS = 'HOSTEL_BOYS', 'Boys Hostel'
    HOSTEL_GIRLS = 'HOSTEL_GIRLS', 'Girls Hostel'
    SHOP_COMPLEX = 'SHOP_COMPLEX', 'Shop Complex'
    TEACHER_QUARTERS = 'TEACHER_QUARTERS', 'Teacher Quarters'

class UnitStatus(models.TextChoices):
    VACANT = 'VACANT', 'Vacant'
    PARTIAL = 'PARTIAL', 'Partially Occupied'
    OCCUPIED = 'OCCUPIED', 'Fully Occupied'
    MAINTENANCE = 'MAINTENANCE', 'Under Maintenance'

class BedStatus(models.TextChoices):
    VACANT = 'VACANT', 'Vacant'
    OCCUPIED = 'OCCUPIED', 'Occupied'
    MAINTENANCE = 'MAINTENANCE', 'Under Maintenance'

class OccupantType(models.TextChoices):
    STUDENT = 'STUDENT', 'Student'
    TEACHER = 'TEACHER', 'Teacher'
    SHOPKEEPER = 'SHOPKEEPER', 'Shopkeeper'

class AllocationStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    VACATED = 'VACATED', 'Vacated'
    CANCELLED = 'CANCELLED', 'Cancelled'

class AmenityLevel(models.TextChoices):
    BUILDING = 'BUILDING', 'Building'
    BLOCK = 'BLOCK', 'Block'
    UNIT = 'UNIT', 'Unit'

class AmenityValueType(models.TextChoices):
    BOOLEAN = 'BOOLEAN', 'Yes/No'
    NUMBER = 'NUMBER', 'Number'
    TEXT = 'TEXT', 'Text'
