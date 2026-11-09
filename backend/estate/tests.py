"""Run with:  uv run python manage.py test estate -v 2"""
from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from . import services
from .constants import AmenityLevel, AmenityValueType, PropertyType
from .models import Allocation, AmenityDefinition, AmenityValue, Bed, Building, Occupant, Unit

User = get_user_model()
BASE = '/api/estate'


def make_user(name, group=None, **kw):
    u = User.objects.create_user(name, password='pw', **kw)
    if group:
        u.groups.add(Group.objects.get_or_create(name=group)[0])
    return u


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user('admin', 'estate_admin')
        cls.assistant = make_user('assistant', 'hall_assistant')
        cls.outsider = make_user('outsider')

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    # -- factories
    def building(self, ptype=PropertyType.HOSTEL_BOYS, name='B1'):
        return Building.objects.create(name=name, property_type=ptype, created_by=self.admin)

    def unit(self, building, number='101', capacity=1):
        return services.create_unit(building=building, number=number, capacity=capacity, created_by=self.admin)

    def person(self, otype='STUDENT', gender='M', name='Asha'):
        return Occupant.objects.create(occupant_type=otype, full_name=name, gender=gender, created_by=self.admin)

    def allocate(self, occ, unit, bed=None, **kw):
        return services.allocate_unit(occupant=occ, unit=unit, bed=bed, allocated_by=self.admin, **kw)


class UnitAndBedTests(Base):
    def test_hostel_unit_autogenerates_beds(self):
        u = self.unit(self.building(), capacity=4)
        self.assertEqual(list(u.beds.values_list('bed_number', flat=True)), ['1', '2', '3', '4'])

    def test_single_unit_has_no_beds(self):
        u = self.unit(self.building(PropertyType.SHOP_COMPLEX), '5')
        self.assertEqual(u.beds.count(), 0)

    def test_capacity_gt_1_rejected_outside_hostels(self):
        with self.assertRaises(ValidationError):
            self.unit(self.building(PropertyType.SHOP_COMPLEX), '5', capacity=2)

    def test_add_and_remove_bed_keeps_capacity_in_sync(self):
        u = self.unit(self.building(), capacity=3)
        bed = services.add_bed(u)
        u.refresh_from_db()
        self.assertEqual((u.capacity, bed.bed_number), (4, '4'))
        services.remove_bed(bed)
        u.refresh_from_db()
        self.assertEqual(u.capacity, 3)
        self.assertEqual(u.beds.filter(is_active=True).count(), 3)

    def test_removed_bed_number_is_reused_on_add(self):
        u = self.unit(self.building(), capacity=3)
        b = u.beds.get(bed_number='3')
        services.remove_bed(b)
        again = services.add_bed(u)
        self.assertEqual(again.pk, b.pk)  # reactivated, no unique clash

    def test_cannot_remove_occupied_bed(self):
        u = self.unit(self.building(), capacity=3)
        bed = u.beds.first()
        self.allocate(self.person(), u, bed)
        with self.assertRaises(ValidationError):
            services.remove_bed(bed)

    def test_capacity_down_blocked_without_free_beds(self):
        u = self.unit(self.building(), capacity=2)
        for i, bed in enumerate(u.beds.all()):
            self.allocate(self.person(name=f's{i}'), u, bed)
        with self.assertRaises(ValidationError):
            services.update_unit(u, capacity=1)

    def test_capacity_up_and_down_with_free_beds(self):
        u = self.unit(self.building(), capacity=2)
        services.update_unit(u, capacity=4)
        self.assertEqual(u.beds.filter(is_active=True).count(), 4)
        services.update_unit(u, capacity=3)
        self.assertEqual(u.beds.filter(is_active=True).count(), 3)

    def test_cannot_cross_single_multi_with_active_allocation(self):
        u = self.unit(self.building(), capacity=2)
        self.allocate(self.person(), u, u.beds.first())
        with self.assertRaises(ValidationError):
            services.update_unit(u, capacity=1)

    def test_rename_bed_unique(self):
        u = self.unit(self.building(), capacity=2)
        with self.assertRaises(ValidationError):
            services.rename_bed(u.beds.get(bed_number='1'), '2')

    def test_bulk_create_units(self):
        b = self.building()
        units = services.bulk_create_units(building=b, start=101, end=105, capacity=4, created_by=self.admin)
        self.assertEqual(len(units), 5)
        self.assertEqual(Bed.objects.filter(unit__building=b).count(), 20)
        with self.assertRaises(ValidationError):
            services.bulk_create_units(building=b, start=103, end=106, created_by=self.admin)


class AllocationTests(Base):
    def test_status_flow_for_hostel_room(self):
        u = self.unit(self.building(), capacity=2)
        b1, b2 = u.beds.all()
        a1 = self.allocate(self.person(name='a'), u, b1)
        u.refresh_from_db(); b1.refresh_from_db()
        self.assertEqual((u.status, b1.status), ('PARTIAL', 'OCCUPIED'))
        a2 = self.allocate(self.person(name='b'), u, b2)
        u.refresh_from_db()
        self.assertEqual(u.status, 'OCCUPIED')
        services.vacate_allocation(a1)
        u.refresh_from_db(); b1.refresh_from_db()
        self.assertEqual((u.status, b1.status), ('PARTIAL', 'VACANT'))
        services.vacate_allocation(a2)
        u.refresh_from_db()
        self.assertEqual(u.status, 'VACANT')
        a1.refresh_from_db()
        self.assertEqual(a1.status, 'VACATED')
        self.assertIsNotNone(a1.end_date)

    def test_double_booking_bed(self):
        u = self.unit(self.building(), capacity=2)
        bed = u.beds.first()
        self.allocate(self.person(name='a'), u, bed)
        with self.assertRaisesMessage(ValidationError, 'already occupied'):
            self.allocate(self.person(name='b'), u, bed)

    def test_double_booking_single_unit(self):
        u = self.unit(self.building(PropertyType.TEACHER_QUARTERS), 'Q1')
        self.allocate(self.person('TEACHER', '', 't1'), u)
        with self.assertRaises(ValidationError):
            self.allocate(self.person('TEACHER', '', 't2'), u)

    def test_bed_required_and_forbidden(self):
        hostel = self.unit(self.building(), capacity=2)
        with self.assertRaises(ValidationError):
            self.allocate(self.person(), hostel)
        quarter = self.unit(self.building(PropertyType.TEACHER_QUARTERS, 'Q'), 'Q1')
        bed = hostel.beds.first()
        with self.assertRaises(ValidationError):
            self.allocate(self.person('TEACHER', '', 't'), quarter, bed)

    def test_occupant_type_must_match_building(self):
        shop = self.unit(self.building(PropertyType.SHOP_COMPLEX, 'S'), '1')
        with self.assertRaises(ValidationError):
            self.allocate(self.person('STUDENT', 'M'), shop)

    def test_gender_rules(self):
        boys = self.unit(self.building(PropertyType.HOSTEL_BOYS, 'Boys'), capacity=2)
        girls = self.unit(self.building(PropertyType.HOSTEL_GIRLS, 'Girls'), capacity=2)
        with self.assertRaises(ValidationError):
            self.allocate(self.person(gender='F'), boys, boys.beds.first())
        with self.assertRaises(ValidationError):
            self.allocate(self.person(gender='M', name='m'), girls, girls.beds.first())
        self.allocate(self.person(gender='F', name='f'), girls, girls.beds.first())

    def test_student_one_active_allocation(self):
        u = self.unit(self.building(), capacity=2)
        s = self.person()
        a = self.allocate(s, u, u.beds.first())
        with self.assertRaises(ValidationError):
            self.allocate(s, u, u.beds.last())
        services.vacate_allocation(a)
        self.allocate(s, u, u.beds.last())  # fine after move-out

    def test_shopkeeper_can_hold_several_shops(self):
        b = self.building(PropertyType.SHOP_COMPLEX, 'S')
        owner = self.person('SHOPKEEPER', '', 'owner')
        self.allocate(owner, self.unit(b, '1'))
        self.allocate(owner, self.unit(b, '2'))
        self.assertEqual(owner.allocations.filter(status='ACTIVE').count(), 2)

    def test_maintenance_blocks_allocation(self):
        u = self.unit(self.building(), capacity=2)
        bed = u.beds.first()
        services.set_bed_maintenance(bed, True)
        with self.assertRaises(ValidationError):
            self.allocate(self.person(), u, bed)
        services.set_unit_maintenance(u, True)
        with self.assertRaises(ValidationError):
            self.allocate(self.person(name='x'), u, u.beds.last())

    def test_maintenance_bed_does_not_stop_unit_being_full(self):
        u = self.unit(self.building(), capacity=2)
        b1, b2 = u.beds.all()
        services.set_bed_maintenance(b2, True)
        self.allocate(self.person(), u, b1)
        u.refresh_from_db()
        self.assertEqual(u.status, 'OCCUPIED')

    def test_vacate_twice_fails_and_end_before_start_fails(self):
        u = self.unit(self.building(PropertyType.TEACHER_QUARTERS), 'Q1')
        a = self.allocate(self.person('TEACHER', '', 't'), u, start_date=date(2026, 5, 10))
        with self.assertRaises(ValidationError):
            services.vacate_allocation(a, end_date=date(2026, 5, 1))
        services.vacate_allocation(a, end_date=date(2026, 6, 1))
        with self.assertRaises(ValidationError):
            services.vacate_allocation(a)

    def test_cancel(self):
        u = self.unit(self.building(PropertyType.TEACHER_QUARTERS), 'Q1')
        a = self.allocate(self.person('TEACHER', '', 't'), u)
        services.cancel_allocation(a)
        u.refresh_from_db(); a.refresh_from_db()
        self.assertEqual((a.status, u.status), ('CANCELLED', 'VACANT'))

    def test_sync_status_repairs_drift(self):
        u = self.unit(self.building(), capacity=2)
        self.allocate(self.person(), u, u.beds.first())
        Unit.objects.filter(pk=u.pk).update(status='VACANT')
        Bed.objects.update(status='VACANT')
        self.assertGreater(services.sync_status(), 0)
        u.refresh_from_db()
        self.assertEqual(u.status, 'PARTIAL')

    def test_soft_delete_blocked_by_active_allocation(self):
        b = self.building(PropertyType.SHOP_COMPLEX, 'S')
        u = self.unit(b, '1')
        occ = self.person('SHOPKEEPER', '', 'o')
        a = self.allocate(occ, u)
        for obj in (b, u, occ):
            with self.assertRaises(ValidationError):
                services.deactivate(obj)
        services.vacate_allocation(a)
        services.deactivate(u)
        self.assertFalse(Unit.objects.get(pk=u.pk).is_active)


class AmenityTests(Base):
    def definition(self, name='WiFi', level=AmenityLevel.BUILDING, vt=AmenityValueType.BOOLEAN, types=None):
        return AmenityDefinition.objects.create(
            name=name, level=level, value_type=vt, applicable_property_types=types or [], created_by=self.admin,
        )

    def test_upsert_overwrites(self):
        b = self.building()
        d = self.definition()
        services.set_amenity_value(d, True, building=b)
        services.set_amenity_value(d, False, building=b)
        self.assertEqual(AmenityValue.objects.filter(building=b).count(), 1)
        self.assertIs(AmenityValue.objects.get(building=b).value_boolean, False)

    def test_level_mismatch_rejected(self):
        d = self.definition(level=AmenityLevel.UNIT)
        with self.assertRaises(ValidationError):
            services.set_amenity_value(d, True, building=self.building())

    def test_property_type_restriction(self):
        d = self.definition(name='Geyser', types=[PropertyType.HOSTEL_GIRLS])
        with self.assertRaises(ValidationError):
            services.set_amenity_value(d, True, building=self.building(PropertyType.HOSTEL_BOYS))
        services.set_amenity_value(d, True, building=self.building(PropertyType.HOSTEL_GIRLS, 'G'))

    def test_type_coercion_and_rejection(self):
        b = self.building()
        n = self.definition('Floors', vt=AmenityValueType.NUMBER)
        services.set_amenity_value(n, '3', building=b)
        with self.assertRaises(ValidationError):
            services.set_amenity_value(n, 'abc', building=b)
        flag = self.definition('Lift')
        with self.assertRaises(ValidationError):
            services.set_amenity_value(flag, 'maybe', building=b)

    def test_lock_rule_via_api(self):
        d = self.definition()
        services.set_amenity_value(d, True, building=self.building())
        r = self.api.patch(f'{BASE}/amenity-definitions/{d.pk}/', {'value_type': 'TEXT'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.api.patch(f'{BASE}/amenity-definitions/{d.pk}/', {'name': 'Internet'}, format='json')
        self.assertEqual(r.status_code, 200)


class ApiTests(Base):
    def wizard_payload(self, **extra):
        wifi = AmenityDefinition.objects.create(
            name='WiFi', level='BUILDING', value_type='BOOLEAN', created_by=self.admin)
        ac = AmenityDefinition.objects.create(
            name='AC', level='UNIT', value_type='BOOLEAN', created_by=self.admin)
        payload = {
            'name': 'Gaash Boys Hostel', 'property_type': 'HOSTEL_BOYS', 'location': 'Campus',
            'amenities': [{'definition': wifi.pk, 'value': True}],
            'blocks': [{'name': 'A', 'units': [
                {'number': '101', 'capacity': 3, 'amenities': [{'definition': ac.pk, 'value': True}]},
                {'number': '102', 'capacity': 2},
            ]}],
            'units': [{'number': 'G1', 'capacity': 1}],
        }
        payload.update(extra)
        return payload

    def test_nested_building_create(self):
        r = self.api.post(f'{BASE}/buildings/', self.wizard_payload(), format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['created_by'], self.admin.pk)
        self.assertEqual(r.data['amenities'][0]['value'], True)
        self.assertEqual(Unit.objects.count(), 3)
        self.assertEqual(Bed.objects.count(), 5)
        self.assertIsNone(Unit.objects.get(number='G1').block)

    def test_nested_create_is_atomic(self):
        payload = self.wizard_payload()
        payload['blocks'][0]['units'].append({'number': 'X', 'capacity': 0})
        r = self.api.post(f'{BASE}/buildings/', payload, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Building.objects.count(), 0)

    def test_nested_create_rejects_bad_amenity_without_leaving_rows(self):
        payload = self.wizard_payload()
        payload['units'][0]['amenities'] = [payload['amenities'][0]]  # BUILDING-level on a unit
        r = self.api.post(f'{BASE}/buildings/', payload, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual((Building.objects.count(), Unit.objects.count()), (0, 0))

    def test_duplicate_unit_numbers_rejected(self):
        payload = self.wizard_payload()
        payload['units'].append({'number': '101'})
        r = self.api.post(f'{BASE}/buildings/', payload, format='json')
        self.assertEqual(r.status_code, 400)

    def test_unit_api_labels_and_beds(self):
        b = self.building()
        r = self.api.post(f'{BASE}/units/', {'building': b.pk, 'number': '201', 'capacity': 3}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['number_label'], 'Room No')
        self.assertEqual([x['bed_number'] for x in r.data['beds']], ['1', '2', '3'])
        self.assertEqual(r.data['status'], 'VACANT')
        shop = self.building(PropertyType.SHOP_COMPLEX, 'S')
        r = self.api.post(f'{BASE}/units/', {'building': shop.pk, 'number': '7'}, format='json')
        self.assertEqual(r.data['number_label'], 'Shop No')

    def test_unit_status_not_client_writable(self):
        u = self.unit(self.building())
        r = self.api.patch(f'{BASE}/units/{u.pk}/', {'status': 'OCCUPIED'}, format='json')
        self.assertEqual(r.status_code, 200)
        u.refresh_from_db()
        self.assertEqual(u.status, 'VACANT')

    def test_unit_patch_capacity_adds_beds(self):
        u = self.unit(self.building(), capacity=2)
        r = self.api.patch(f'{BASE}/units/{u.pk}/', {'capacity': 4}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data['beds']), 4)

    def test_unit_bulk_endpoint(self):
        b = self.building()
        r = self.api.post(f'{BASE}/units/bulk/', {'building': b.pk, 'start': 101, 'end': 103, 'capacity': 4}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(len(r.data), 3)

    def test_allocation_api_lifecycle_and_room_endpoint(self):
        b = self.building()
        u = self.unit(b, capacity=2)
        s = self.person()
        r = self.api.post(f'{BASE}/allocations/', {
            'occupant': s.pk, 'unit': u.pk, 'bed': u.beds.first().pk, 'start_date': '2026-09-01',
            'allocated_by': 999, 'status': 'VACATED'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['allocated_by'], self.admin.pk)   # client value ignored
        self.assertEqual(r.data['status'], 'ACTIVE')
        alloc_id = r.data['id']

        room = self.api.get(f'{BASE}/occupants/{s.pk}/room/')
        self.assertEqual(room.status_code, 200)
        self.assertEqual(len(room.data['allocations']), 1)
        self.assertEqual(room.data['allocations'][0]['unit_number'], '101')

        # no update / delete on allocations
        self.assertEqual(self.api.delete(f'{BASE}/allocations/{alloc_id}/').status_code, 405)
        self.assertEqual(self.api.patch(f'{BASE}/allocations/{alloc_id}/', {}, format='json').status_code, 405)

        r = self.api.post(f'{BASE}/allocations/{alloc_id}/vacate/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['status'], 'VACATED')
        self.assertEqual(self.api.get(f'{BASE}/occupants/{s.pk}/room/').data['allocations'], [])

    def test_allocation_api_returns_400_not_500(self):
        u = self.unit(self.building(), capacity=2)
        s = self.person()
        r = self.api.post(f'{BASE}/allocations/', {'occupant': s.pk, 'unit': u.pk}, format='json')  # bed missing
        self.assertEqual(r.status_code, 400)
        self.assertIn('bed', r.data)

    def test_occupant_requires_gender_for_students(self):
        r = self.api.post(f'{BASE}/occupants/', {'occupant_type': 'STUDENT', 'full_name': 'X'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.api.post(f'{BASE}/occupants/', {'occupant_type': 'TEACHER', 'full_name': 'T'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['created_by'], self.admin.pk)

    def test_soft_delete_and_list_filter(self):
        b = self.building()
        self.assertEqual(self.api.delete(f'{BASE}/buildings/{b.pk}/').status_code, 204)
        self.assertTrue(Building.objects.filter(pk=b.pk).exists())
        self.assertEqual(self.api.get(f'{BASE}/buildings/').data['count'], 0)
        self.assertEqual(self.api.get(f'{BASE}/buildings/?is_active=all').data['count'], 1)
        self.assertEqual(self.api.post(f'{BASE}/buildings/{b.pk}/activate/').status_code, 200)
        self.assertEqual(self.api.get(f'{BASE}/buildings/').data['count'], 1)

    def test_bed_endpoints(self):
        u = self.unit(self.building(), capacity=3)
        r = self.api.post(f'{BASE}/beds/', {'unit': u.pk}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['bed_number'], '4')
        bed_id = r.data['id']
        self.assertEqual(self.api.patch(f'{BASE}/beds/{bed_id}/', {'bed_number': 'D'}, format='json').data['bed_number'], 'D')
        r = self.api.post(f'{BASE}/beds/{bed_id}/maintenance/', {'maintenance': True}, format='json')
        self.assertEqual(r.data['status'], 'MAINTENANCE')
        self.assertEqual(self.api.delete(f'{BASE}/beds/{bed_id}/').status_code, 204)
        u.refresh_from_db()
        self.assertEqual(u.capacity, 3)

    def test_amenity_value_post_is_upsert(self):
        b = self.building()
        d = AmenityDefinition.objects.create(name='Floors', level='BUILDING', value_type='NUMBER', created_by=self.admin)
        r1 = self.api.post(f'{BASE}/amenity-values/', {'definition': d.pk, 'building': b.pk, 'value_number': '3'}, format='json')
        r2 = self.api.post(f'{BASE}/amenity-values/', {'definition': d.pk, 'building': b.pk, 'value_number': '5'}, format='json')
        self.assertEqual((r1.status_code, r2.status_code), (201, 201), (r1.data, r2.data))
        self.assertEqual(AmenityValue.objects.count(), 1)
        self.assertEqual(r2.data['value'], 5.0)
        r = self.api.patch(f'{BASE}/amenity-values/{r2.data["id"]}/', {'value_number': '7'}, format='json')
        self.assertEqual(r.data['value'], 7.0)
        bad = self.api.post(f'{BASE}/amenity-values/', {'definition': d.pk, 'building': b.pk, 'value_text': 'x'}, format='json')
        self.assertEqual(bad.status_code, 400)

    def test_stats(self):
        u = self.unit(self.building(), capacity=2)
        self.allocate(self.person(), u, u.beds.first())
        r = self.api.get(f'{BASE}/stats/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['units']['by_status'], {'PARTIAL': 1})
        self.assertEqual(r.data['beds']['by_status']['OCCUPIED'], 1)
        self.assertEqual(r.data['active_allocations'], 1)

    def test_bad_filter_value_is_400(self):
        r = self.api.get(f'{BASE}/units/?building=abc')
        self.assertEqual(r.status_code, 400)


class PermissionTests(Base):
    def test_anonymous_and_outsider_denied(self):
        anon = APIClient()
        self.assertIn(anon.get(f'{BASE}/buildings/').status_code, (401, 403))
        out = APIClient(); out.force_authenticate(self.outsider)
        for path in ('buildings', 'units', 'beds', 'occupants', 'allocations', 'amenity-values', 'stats'):
            self.assertEqual(out.get(f'{BASE}/{path}/').status_code, 403, path)

    def test_superuser_counts_as_admin(self):
        su = User.objects.create_superuser('root', password='pw')
        c = APIClient(); c.force_authenticate(su)
        self.assertEqual(c.get(f'{BASE}/buildings/').status_code, 200)

    def test_assistant_read_only_on_structure(self):
        b = self.building()
        u = self.unit(b, capacity=2)
        c = APIClient(); c.force_authenticate(self.assistant)
        self.assertEqual(c.get(f'{BASE}/buildings/').status_code, 200)
        self.assertEqual(c.get(f'{BASE}/units/{u.pk}/').status_code, 200)
        self.assertEqual(c.get(f'{BASE}/amenity-definitions/').status_code, 200)
        self.assertEqual(c.post(f'{BASE}/buildings/', {'name': 'x', 'property_type': 'HOSTEL_BOYS'}, format='json').status_code, 403)
        self.assertEqual(c.patch(f'{BASE}/units/{u.pk}/', {'floor': '2'}, format='json').status_code, 403)
        self.assertEqual(c.delete(f'{BASE}/buildings/{b.pk}/').status_code, 403)
        self.assertEqual(c.post(f'{BASE}/units/bulk/', {}, format='json').status_code, 403)
        self.assertEqual(c.post(f'{BASE}/amenity-definitions/', {}, format='json').status_code, 403)
        self.assertEqual(c.delete(f'{BASE}/occupants/1/').status_code, 403)

    def test_assistant_can_allocate_vacate_and_manage_beds(self):
        u = self.unit(self.building(), capacity=2)
        s = self.person()
        c = APIClient(); c.force_authenticate(self.assistant)
        r = c.post(f'{BASE}/occupants/', {'occupant_type': 'STUDENT', 'full_name': 'New', 'gender': 'M'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        r = c.post(f'{BASE}/allocations/', {'occupant': s.pk, 'unit': u.pk, 'bed': u.beds.first().pk}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['allocated_by'], self.assistant.pk)
        self.assertEqual(c.post(f'{BASE}/allocations/{r.data["id"]}/vacate/', {}, format='json').status_code, 200)
        self.assertEqual(c.post(f'{BASE}/beds/', {'unit': u.pk}, format='json').status_code, 201)
        self.assertEqual(c.get(f'{BASE}/stats/').status_code, 200)
