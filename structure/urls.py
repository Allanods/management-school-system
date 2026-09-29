from django.urls import path

from .views import (
    AssignmentCreateView,
    AssignmentDeleteView,
    AssignmentListView,
    AssignmentUpdateView,
    ClassCreateView,
    ClassDetailView,
    ClassListView,
    ClassStreamCreateView,
    ClassStreamDetailView,
    ClassStreamListView,
    ClassStreamUpdateView,
    ClassUpdateView,
    StreamCreateView,
    StreamListView,
    StreamUpdateView,
    SubjectCreateView,
    SubjectListView,
    SubjectUpdateView,
)

app_name = 'structure'

urlpatterns = [
    path('classes/', ClassListView.as_view(), name='class_list'),
    path('classes/add/', ClassCreateView.as_view(), name='class_add'),
    path('classes/<int:pk>/', ClassDetailView.as_view(), name='class_detail'),
    path('classes/<int:pk>/edit/', ClassUpdateView.as_view(), name='class_edit'),
    path('streams/', StreamListView.as_view(), name='stream_list'),
    path('streams/add/', StreamCreateView.as_view(), name='stream_add'),
    path('streams/<int:pk>/edit/', StreamUpdateView.as_view(), name='stream_edit'),
    path('class-streams/', ClassStreamListView.as_view(), name='classstream_list'),
    path('class-streams/add/', ClassStreamCreateView.as_view(), name='classstream_add'),
    path(
        'class-streams/<int:pk>/',
        ClassStreamDetailView.as_view(),
        name='classstream_detail',
    ),
    path(
        'class-streams/<int:pk>/edit/',
        ClassStreamUpdateView.as_view(),
        name='classstream_edit',
    ),
    path('subjects/', SubjectListView.as_view(), name='subject_list'),
    path('subjects/add/', SubjectCreateView.as_view(), name='subject_add'),
    path('subjects/<int:pk>/edit/', SubjectUpdateView.as_view(), name='subject_edit'),
    path('assignments/', AssignmentListView.as_view(), name='assignment_list'),
    path('assignments/add/', AssignmentCreateView.as_view(), name='assignment_add'),
    path(
        'assignments/<int:pk>/edit/',
        AssignmentUpdateView.as_view(),
        name='assignment_edit',
    ),
    path(
        'assignments/<int:pk>/delete/',
        AssignmentDeleteView.as_view(),
        name='assignment_delete',
    ),
]