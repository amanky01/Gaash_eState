from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

app_name = 'estate'

router = DefaultRouter()
router.register('buildings', views.BuildingViewSet, basename='building')
router.register('blocks', views.BlockViewSet, basename='block')
router.register('units', views.UnitViewSet, basename='unit')
router.register('beds', views.BedViewSet, basename='bed')
router.register('occupants', views.OccupantViewSet, basename='occupant')
router.register('allocations', views.AllocationViewSet, basename='allocation')
router.register('amenity-definitions', views.AmenityDefinitionViewSet, basename='amenity-definition')
router.register('amenity-values', views.AmenityValueViewSet, basename='amenity-value')

urlpatterns = [
    path('stats/', views.StatsView.as_view(), name='stats'),
    path('', include(router.urls)),
]
