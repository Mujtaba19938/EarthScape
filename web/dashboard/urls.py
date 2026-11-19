"""Dashboard URLs: one per page, plus the actions each page posts."""
from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("overview/", views.overview, name="overview"),
    path("analytics/", views.analytics, name="analytics"),
    path("monitor/", views.monitor, name="monitor"),
    path("monitor/poll/", views.poll_now, name="poll"),
    path("data/", views.data_page, name="data"),
    path("data/upload/", views.upload, name="upload"),
    path("hadoop/", views.hadoop, name="hadoop"),
    path("hadoop/jobs/<str:application_id>/", views.job_detail, name="job_detail"),
    path("hadoop/run/<str:name>/", views.run_job, name="run_job"),
    path("ml/", views.ml, name="ml"),
    path("ml/retrain/", views.retrain, name="retrain"),
    path("alerts/", views.alerts, name="alerts"),
    path("alerts/rules/new/", views.create_rule, name="create_rule"),
    path("alerts/rules/<str:rule_id>/delete/", views.delete_rule, name="delete_rule"),
    path("alerts/<str:alert_id>/", views.update_alert, name="update_alert"),
    path("reports/", views.reports, name="reports"),
    path("reports/download/", views.download_report, name="download_report"),
    path("support/", views.support, name="support"),
    path("support/<str:ticket_id>/", views.update_ticket, name="update_ticket"),
    path("status/", views.status, name="status"),
    path("status/maintenance/", views.save_maintenance, name="maintenance"),
    path("architecture/", views.architecture, name="architecture"),
    path("search/", views.search, name="search"),
    path("notifications/read/", views.read_notifications, name="read_notifications"),
]
