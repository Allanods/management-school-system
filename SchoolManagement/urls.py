from django.contrib import admin
from django.urls import include, path

from accounts.views import home

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home, name='home'),
    path('accounts/', include('accounts.urls')),
    path('students/', include('students.urls')),
    path('teachers/', include('teachers.urls')),
    path('academics/', include('academics.urls')),
    path('attendance/', include('attendance.urls')),
    path('fees/', include('fees.urls')),
    path('announcements/', include('communication.urls')),
    path('reports/', include('reports.urls')),
    path('', include('structure.urls')),
]

handler403 = 'SchoolManagement.views.handler403'
handler404 = 'SchoolManagement.views.handler404'
handler500 = 'SchoolManagement.views.handler500'