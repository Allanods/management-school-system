from django.urls import path

from .views import (
    MyTeacherProfileView,
    TeacherCreateView,
    TeacherDetailView,
    TeacherListView,
    TeacherUpdateView,
)

app_name = 'teachers'

urlpatterns = [
    path('', TeacherListView.as_view(), name='list'),
    path('profile/', MyTeacherProfileView.as_view(), name='profile'),
    path('add/', TeacherCreateView.as_view(), name='add'),
    path('<int:pk>/', TeacherDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', TeacherUpdateView.as_view(), name='edit'),
]