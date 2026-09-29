from django.urls import path

from .views import (
    AccountLookupView,
    ChargeCreateView,
    ChargeEditView,
    ChildFeesView,
    FeeStructureCreateView,
    FeeStructureDeactivateView,
    FeeStructureEditView,
    FeeStructureListView,
    FinanceDashboardView,
    GenerateChargesView,
    ParentChildrenView,
    PaymentCreateView,
    PaymentEditView,
    PaymentHistoryView,
    PaymentVoidView,
    StudentAccountDetailView,
    StudentAccountListView,
)

app_name = 'fees'

urlpatterns = [
    path('', FinanceDashboardView.as_view(), name='home'),
    path('structures/', FeeStructureListView.as_view(), name='structures'),
    path('structures/add/', FeeStructureCreateView.as_view(), name='structure_add'),
    path(
        'structures/<int:pk>/edit/',
        FeeStructureEditView.as_view(), name='structure_edit',
    ),
    path(
        'structures/<int:pk>/deactivate/',
        FeeStructureDeactivateView.as_view(), name='structure_deactivate',
    ),
    path('accounts/', StudentAccountListView.as_view(), name='accounts'),
    path('accounts/lookup/', AccountLookupView.as_view(), name='account_lookup'),
    path('accounts/generate/', GenerateChargesView.as_view(), name='generate'),
    path('accounts/<int:pk>/', StudentAccountDetailView.as_view(), name='account_detail'),
    path('accounts/<int:pk>/charges/add/', ChargeCreateView.as_view(), name='charge_add'),
    path('charges/<int:pk>/edit/', ChargeEditView.as_view(), name='charge_edit'),
    path('accounts/<int:pk>/payments/add/', PaymentCreateView.as_view(), name='payment_add'),
    path('payments/', PaymentHistoryView.as_view(), name='payment_list'),
    path('payments/<int:pk>/edit/', PaymentEditView.as_view(), name='payment_edit'),
    path('payments/<int:pk>/void/', PaymentVoidView.as_view(), name='payment_void'),
    path('my-children/', ParentChildrenView.as_view(), name='my_children'),
    path('my-children/<int:pk>/', ChildFeesView.as_view(), name='child_fees'),
]