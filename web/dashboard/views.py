"""Dashboard pages. Each page has its own URL and template; actions post and redirect back."""
from django.contrib import messages
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from pymongo.errors import PyMongoError

from accounts.auth import admin_required, current_user, login_required
from earthscape import config
from earthscape.crypto import encrypt
from earthscape.db import db, notify, now, object_id

from . import ask, cluster, data, live


#----------------------------home--------------------------------------

@login_required
def home(request):
    context = {
        "page": "landing",
        "stats": data.landing_stats(),
    }
    return render(request, "dashboard/home.html", context)


@login_required
def overview(request):
    jobs = data.jobs()
    context = {
        "page": "dashboard",
        "stats": data.dashboard_stats(),
        "global_chart": data.global_chart(),
        "anomalies": data.station_anomalies(8),
        "jobs": jobs["jobs"][:5],
        "yarn_online": jobs["yarn_online"],
    }
    return render(request, "dashboard/overview.html", context)


#----------------------------climate analytics--------------------------------------

@login_required
def analytics(request):
    zone = request.GET.get("zone", "Glob")
    variable = request.GET.get("variable", "anomaly")
    # Unknown choice resets
    if zone not in dict(data.ZONE_OPTIONS) or variable not in dict(data.VARIABLES):
        zone, variable = "Glob", "anomaly"

    graph, message = data.analytics_chart(zone, variable)
    band = "" if zone == "Glob" else " (%s band)" % zone
    title = "%s - %s%s" % (dict(data.VARIABLES)[variable], dict(data.ZONE_OPTIONS)[zone], band)

    context = {
        "page": "analytics",
        "zone": zone,
        "variable": variable,
        "zones": data.ZONE_OPTIONS,
        "variables": data.VARIABLES,
        "title": title,
        "chart": graph,
        "message": message,
        "summary": data.zone_summary(),
        "summary_year": data.ANALYTICS_YEAR,
    }
    return render(request, "dashboard/analytics.html", context)


#----------------------------live monitor--------------------------------------

@login_required
def monitor(request):
    location = request.GET.get("location", config.LIVE_LOCATION_NAMES[0])
    metric = request.GET.get("metric", data.LIVE_METRICS[0][0])
    if location not in config.LIVE_LOCATION_NAMES or metric not in dict(data.LIVE_METRICS):
        location, metric = config.LIVE_LOCATION_NAMES[0], data.LIVE_METRICS[0][0]

    status = live.status()
    context = {
        "page": "monitoring",
        "status": status,
        "status_text": data.live_status_text(status),
        "batch_text": data.live_batch_text(status),
        "cards": data.live_cards(),
        "sensors": data.air_quality_sensors(),
        "location": location,
        "metric": metric,
        "locations": config.LIVE_LOCATION_NAMES,
        "metrics": data.LIVE_METRICS,
        "chart": data.live_history_chart(location, metric),
        "refresh_seconds": 60,
    }
    return render(request, "dashboard/monitor.html", context)


@admin_required
@require_POST
def poll_now(request):
    record, error = live.poll_now(current_user(request)["name"])
    if error:
        messages.error(request, error)
    else:
        messages.success(request, "Checked %s cities: %s new alerts, %s cleared." % (
            record["readings"], record["alerts_fired"], record["alerts_cleared"]))
    return redirect("dashboard:monitor")


#----------------------------data explorer and upload--------------------------------------

@login_required
def data_page(request):
    context = {
        "page": "data",
        "datasets": data.datasets(),
        "quality": data.quality_rows(),
        "accept": ",".join(sorted(data.UPLOAD_SIGNATURES)),
    }
    return render(request, "dashboard/data.html", context)


@admin_required
@require_POST
def upload(request):
    uploaded = request.FILES.get("file")
    if not uploaded:
        messages.error(request, "Choose a file to upload.")
        return redirect("dashboard:data")

    admin = current_user(request)
    try:
        name = data.upload_dataset(uploaded, admin)
    except data.UploadError as error:
        messages.error(request, str(error))
        return redirect("dashboard:data")

    notify("%s uploaded dataset %s." % (admin["name"], name))
    messages.success(request, "%s stored in HDFS." % name)
    return redirect("dashboard:data")


#----------------------------hadoop cluster--------------------------------------

@login_required
def hadoop(request):
    jobs = data.jobs()
    context = {
        "page": "hadoop",
        "stats": data.cluster_stats(),
        "jobs": jobs,
        "job_running": cluster.job_running(),
        # Refresh while running
        "refresh_seconds": 5 if jobs["any_running"] else None,
    }
    return render(request, "dashboard/hadoop.html", context)


@login_required
def job_detail(request, application_id):
    job = data.job_detail(application_id)
    if not job:
        raise Http404("YARN has no record of this job.")
    context = {"page": "hadoop", "job": job}
    return render(request, "dashboard/job_detail.html", context)


@admin_required
@require_POST
def run_job(request, name):
    spec = cluster.job_spec(name)
    if not spec:
        raise Http404("Unknown job.")
    if cluster.start_job(spec, current_user(request)["name"]):
        messages.success(request, "Started %s. It will appear below shortly." % name)
    else:
        messages.error(request, "A job started from here is already running.")
    return redirect("dashboard:hadoop")


#----------------------------ml models and ask--------------------------------------

@login_required
def ml(request):
    series = request.GET.get("series", "Glob")
    if series not in dict(data.ZONE_OPTIONS):
        series = "Glob"
    try:
        horizon = int(request.GET.get("horizon", data.ML_HORIZONS[-1]))
    except ValueError:
        horizon = data.ML_HORIZONS[-1]
    if horizon not in data.ML_HORIZONS:
        horizon = data.ML_HORIZONS[-1]

    # Ask panel
    question = request.POST.get("question", "").strip() if request.method == "POST" else ""
    answer = None
    form_errors = []
    if request.method == "POST":
        if not 2 <= len(question) <= 300:
            form_errors.append("Ask a question between 2 and 300 characters.")
        else:
            answer = data.ask_view(ask.answer_question(question))

    summary = data.ml_summary()
    context = {
        "page": "ml",
        "summary": summary,
        "series": series,
        "horizon": horizon,
        "zones": data.ZONE_OPTIONS,
        "horizons": data.ML_HORIZONS,
        "examples": data.ASK_EXAMPLES,
        "question": question,
        "answer": answer,
        "form_errors": form_errors,
        "forecast": data.forecast(series, horizon) if summary["latest"] else None,
        "anomalies": data.ml_anomalies(),
        "correlations": data.ml_correlations(),
        "refresh_seconds": 5 if summary["retraining"] else None,
    }
    return render(request, "dashboard/ml.html", context)


@admin_required
@require_POST
def retrain(request):
    if cluster.start_training(current_user(request)["name"]):
        messages.success(request, "Training started. This takes about a minute.")
    else:
        messages.error(request, "Training is already running.")
    return redirect("dashboard:ml")


#----------------------------alerts--------------------------------------

@login_required
def alerts(request):
    status = live.status()
    context = {
        "page": "alerts",
        "alerts": data.alerts(),
        "rules": data.alert_rules(),
        "metrics": live.ALERT_METRICS,
        "severities": data.SEVERITIES,
        "status_text": data.live_status_text(status),
        "stale": status["stale"],
    }
    return render(request, "dashboard/alerts.html", context)


@admin_required
@require_POST
def create_rule(request):
    form_data = request.POST
    errors = []

    name = form_data.get("name", "").strip()
    metric = form_data.get("metric", "")
    severity = form_data.get("severity", "")
    try:
        threshold = float(form_data.get("threshold", ""))
    except ValueError:
        threshold = None

    # Rule checks
    if not name or len(name) > 100 or threshold is None:
        errors.append("Enter a name and a number to fire above.")
    if metric not in live.ALERT_METRICS:
        errors.append("Unknown metric.")
    if severity not in data.SEVERITIES:
        errors.append("Unknown severity.")

    if errors:
        messages.error(request, errors[0])
        return redirect("dashboard:alerts")

    db.alert_rules.insert_one({"name": name, "metric": metric, "threshold": threshold, "severity": severity,
                               "created_by": current_user(request)["name"], "created_at": now()})
    messages.success(request, "Rule saved.")
    return redirect("dashboard:alerts")


@admin_required
@require_POST
def delete_rule(request, rule_id):
    if db.alert_rules.delete_one({"_id": object_id(rule_id)}).deleted_count:
        messages.success(request, "Rule deleted.")
    else:
        messages.error(request, "Rule not found.")
    return redirect("dashboard:alerts")


@login_required
@require_POST
def update_alert(request, alert_id):
    status = request.POST.get("status")
    if status not in data.ALERT_STATUSES:
        return HttpResponseBadRequest("Unknown status.")
    result = db.alerts.update_one({"_id": object_id(alert_id)}, {"$set": {
        "status": status, "updated_by": current_user(request)["name"], "updated_at": now()}})
    if not result.matched_count:
        messages.error(request, "Alert not found.")
    return redirect("dashboard:alerts")


#----------------------------reports--------------------------------------

@login_required
def reports(request):
    context = {"page": "reports", "reports": data.report_list()}
    return render(request, "dashboard/reports.html", context)


@login_required
def download_report(request):
    report_id = request.GET.get("report", "")
    file_format = request.GET.get("format", "csv")
    built = data.build_report(report_id, file_format)
    if not built:
        messages.error(request, "This report isn't available in that format. GeoJSON is only for data with map points.")
        return redirect("dashboard:reports")

    body, media_type = built
    response = HttpResponse(body, content_type=media_type)
    response["Content-Disposition"] = 'attachment; filename="%s.%s"' % (report_id, file_format)
    return response


#----------------------------support--------------------------------------

@login_required
def support(request):
    user = current_user(request)

    if request.method == "POST":
        form_data = request.POST
        category = form_data.get("category")
        description = form_data.get("description", "").strip()

        if category not in data.TICKET_CATEGORIES:
            messages.error(request, "Unknown category.")
        elif not description or len(description) > 4000:
            messages.error(request, "Please describe the issue.")
        else:
            # Stored encrypted
            db.tickets.insert_one({"category": category, "description_enc": encrypt(description), "status": "Open",
                                   "created_by": user["id"], "created_by_name": user["name"], "created_at": now()})
            messages.success(request, "Ticket submitted.")
        return redirect("dashboard:support")

    context = {
        "page": "support",
        "tickets": data.tickets(user),
        "categories": data.TICKET_CATEGORIES,
        "statuses": data.TICKET_STATUSES,
    }
    return render(request, "dashboard/support.html", context)


@admin_required
@require_POST
def update_ticket(request, ticket_id):
    status = request.POST.get("status")
    if status not in data.TICKET_STATUSES:
        return HttpResponseBadRequest("Unknown status.")
    key = object_id(ticket_id)
    ticket = db.tickets.find_one({"_id": key})
    if not ticket:
        raise Http404("Ticket not found.")

    db.tickets.update_one({"_id": key}, {"$set": {"status": status, "updated_at": now()}})
    # Tell the owner
    notify('Your ticket "%s" is now %s.' % (ticket["category"], status), ticket["created_by"])
    messages.success(request, "Ticket updated.")
    return redirect("dashboard:support")


#----------------------------system status--------------------------------------

@login_required
def status(request):
    context = {"page": "status", "status": data.system_status()}
    return render(request, "dashboard/status.html", context)


@admin_required
@require_POST
def save_maintenance(request):
    data.set_maintenance(request.POST.get("active") == "on", request.POST.get("message", ""), current_user(request)["name"])
    messages.success(request, "Notice saved.")
    return redirect("dashboard:status")


@login_required
def architecture(request):
    return render(request, "dashboard/architecture.html", {"page": "architecture"})


#----------------------------header tools--------------------------------------

@login_required
def search(request):
    query = request.GET.get("q", "")
    context = {"page": "", "query": query, "results": data.search(query)}
    return render(request, "dashboard/search.html", context)


@login_required
@require_POST
def read_notifications(request):
    data.mark_notifications_read(current_user(request))
    return redirect(request.POST.get("next") or "dashboard:home")


#----------------------------load balancer check--------------------------------------

def health(request):
    """Apache's health check."""
    try:
        db.command("ping")
    except PyMongoError:
        return JsonResponse({"status": "unavailable", "instance": config.INSTANCE_NAME}, status=503)
    return JsonResponse({"status": "ok", "instance": config.INSTANCE_NAME})
