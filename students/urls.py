from django.urls import path

from . import views

app_name = 'students'

urlpatterns = [
    path('', views.StudentListView.as_view(), name='list'),
    path('my-students/', views.StudentListView.as_view(), name='my_students'),
    path('add/', views.StudentCreateView.as_view(), name='add'),
    path('promote/', views.PromoteView.as_view(), name='promote'),
    path('my-children/', views.ParentChildrenView.as_view(), name='my_children'),
    path('parents/', views.ParentListView.as_view(), name='parent_list'),
    path('parents/add/', views.ParentCreateView.as_view(), name='parent_add'),
    path('parents/<int:pk>/', views.ParentDetailView.as_view(), name='parent_detail'),
    path('parents/<int:pk>/edit/', views.ParentUpdateView.as_view(), name='parent_edit'),
    path('<int:pk>/', views.StudentDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', views.StudentUpdateView.as_view(), name='edit'),
]