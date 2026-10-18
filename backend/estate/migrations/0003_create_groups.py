from django.db import migrations

GROUP_NAMES = ['estate_admin', 'hall_assistant']


def create_groups(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    for name in GROUP_NAMES:
        Group.objects.get_or_create(name=name)


def remove_groups(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name__in=GROUP_NAMES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('estate', '0002_constraints_and_validation'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(create_groups, remove_groups),
    ]