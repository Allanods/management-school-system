from django.contrib import admin

from .models import FeeCharge, FeePayment, StudentCharge, StudentFeeAccount


@admin.register(FeeCharge)
class FeeChargeAdmin(admin.ModelAdmin):
    list_display = ('class_stream', 'term', 'description', 'amount', 'is_active')
    list_filter = ('term', 'class_stream', 'is_active')


@admin.register(StudentFeeAccount)
class StudentFeeAccountAdmin(admin.ModelAdmin):
    list_display = ('student', 'term', 'total_charged', 'total_paid', 'balance')
    list_filter = ('term',)
    search_fields = ('student__admission_no', 'student__first_name', 'student__last_name')


@admin.register(StudentCharge)
class StudentChargeAdmin(admin.ModelAdmin):
    list_display = ('student', 'term', 'description', 'amount', 'date', 'created_by')
    list_filter = ('term',)
    search_fields = ('student__admission_no', 'student__first_name', 'description')


@admin.register(FeePayment)
class FeePaymentAdmin(admin.ModelAdmin):
    list_display = (
        'account', 'amount', 'method', 'date', 'receipt_no', 'recorded_by',
        'voided',
    )
    list_filter = ('method', 'voided', 'date')
    search_fields = ('account__student__admission_no', 'receipt_no')