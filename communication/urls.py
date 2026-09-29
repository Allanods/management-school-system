from django.urls import path

from .views import (
    AnnouncementCreateView,
    AnnouncementDeleteView,
    AnnouncementDetailView,
    AnnouncementEditView,
    AnnouncementListView,
    AnnouncementPublishView,
    AnnouncementUnpublishView,
)

app_name = 'announcements'

urlpatterns = [
    path('', AnnouncementListView.as_view(), name='list'),
    path('add/', AnnouncementCreateView.as_view(), name='add'),
    path('<int:pk>/', AnnouncementDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', AnnouncementEditView.as_view(), name='edit'),
    path('<int:pk>/publish/', AnnouncementPublishView.as_view(), name='publish'),
    path(
        '<int:pk>/unpublish/',
        AnnouncementUnpublishView.as_view(), name='unpublish',
    ),
    path('<int:pk>/delete/', AnnouncementDeleteView.as_view(), name='delete'),
]