"""Draws the report's flowcharts and data flow diagrams as PNG files in this folder.

Usage: python docs/diagrams/make_diagrams.py   (with Anaconda's Python, which has matplotlib)
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Ellipse, FancyBboxPatch, Polygon, Rectangle  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
GREEN, DARK, GOLD, PALE, GREY, INK = "#1a814a", "#06190f", "#f6d987", "#e6f2eb", "#f2f3f2", "#040404"


class Diagram:
    def __init__(self, width, height, title):
        self.figure, self.axes = plt.subplots(figsize=(width, height), dpi=170)
        self.axes.set_xlim(0, width)
        self.axes.set_ylim(0, height)
        self.axes.axis("off")
        self.axes.text(0.15, height - 0.3, title, fontsize=13, fontweight="bold", color=INK, va="center")
        self.name_points = {}

    def _label(self, x, y, text, color=INK, size=8.5):
        self.axes.text(x, y, text, ha="center", va="center", fontsize=size, color=color, linespacing=1.25, zorder=4)

    def box(self, name, x, y, text, w=2.1, h=0.7, fill=PALE, color=INK, edge=GREEN):
        self.axes.add_patch(FancyBboxPatch((x - w / 2 + .06, y - h / 2 + .06), w - .12, h - .12, facecolor=fill, edgecolor=edge,
                                           linewidth=1.1, boxstyle="round,pad=0.06", zorder=3))
        self._label(x, y, text, color)
        self.name_points[name] = (x, y, w / 2, h / 2)

    def start(self, name, x, y, text, w=1.7, h=0.5):
        self.axes.add_patch(Ellipse((x, y), w, h, facecolor=DARK, edgecolor=DARK, zorder=3))
        self._label(x, y, text, "#ffffff")
        self.name_points[name] = (x, y, w / 2, h / 2)

    def decision(self, name, x, y, text, w=2.5, h=1.0):
        points = [(x - w / 2, y), (x, y + h / 2), (x + w / 2, y), (x, y - h / 2)]
        self.axes.add_patch(Polygon(points, facecolor=GOLD, edgecolor=INK, linewidth=1, zorder=3))
        self._label(x, y, text, size=8)
        self.name_points[name] = (x, y, w / 2, h / 2)

    def entity(self, name, x, y, text, w=1.9, h=0.7):
        self.axes.add_patch(Rectangle((x - w / 2, y - h / 2), w, h, facecolor=DARK, edgecolor=DARK, zorder=3))
        self._label(x, y, text, "#ffffff")
        self.name_points[name] = (x, y, w / 2, h / 2)

    def process(self, name, x, y, text, r=0.72):
        self.axes.add_patch(Ellipse((x, y), r * 2.25, r * 1.5, facecolor=PALE, edgecolor=GREEN, linewidth=1.2, zorder=3))
        self._label(x, y, text, size=8)
        self.name_points[name] = (x, y, r * 1.125, r * .75)

    def store(self, name, x, y, text, w=2.0, h=0.5):
        self.axes.add_patch(Rectangle((x - w / 2, y - h / 2), w, h, facecolor=GREY, edgecolor=GREY, zorder=2))
        self.axes.plot([x - w / 2, x + w / 2], [y + h / 2, y + h / 2], color=INK, linewidth=1, zorder=3)
        self.axes.plot([x - w / 2, x + w / 2], [y - h / 2, y - h / 2], color=INK, linewidth=1, zorder=3)
        self._label(x, y, text)
        self.name_points[name] = (x, y, w / 2, h / 2)

    def _edge(self, name, target):
        x, y, half_w, half_h = self.name_points[name]
        dx, dy = target[0] - x, target[1] - y
        if abs(dx) * half_h > abs(dy) * half_w:
            return (x + half_w * (1 if dx > 0 else -1), y)
        return (x, y + half_h * (1 if dy > 0 else -1))

    def arrow(self, source, target, text=None, bend=0.0, offset=(0.08, 0.1), start=None, end=None):
        a, b = self.name_points[source], self.name_points[target]
        start, end = start or self._edge(source, b), end or self._edge(target, a)
        self.axes.annotate("", xy=end, xytext=start, zorder=2, arrowprops=dict(
            arrowstyle="-|>", color=INK, linewidth=1, shrinkA=0, shrinkB=0, connectionstyle="arc3,rad=%s" % bend))
        if text:
            self.axes.text((start[0] + end[0]) / 2 + offset[0], (start[1] + end[1]) / 2 + offset[1], text, fontsize=7.2, color="#334155",
                           ha="center", va="center", zorder=5, linespacing=1.2,
                           bbox=dict(facecolor="#ffffff", edgecolor="none", pad=1))

    def save(self, name):
        self.figure.savefig(os.path.join(HERE, name + ".png"), bbox_inches="tight", facecolor="#ffffff", pad_inches=0.12)
        plt.close(self.figure)


def architecture():
    d = Diagram(10, 6.4, "System architecture")
    d.entity("user", 1.2, 5.3, "Browser\nAdmin / Analyst")
    d.box("apache", 3.9, 5.3, "Apache httpd\nHTTPS, load balancing")
    d.box("a", 6.6, 5.7, "FastAPI instance\nport 8000", h=.6)
    d.box("b", 6.6, 4.9, "FastAPI instance\nport 8001", h=.6)
    d.box("mongo", 8.9, 3.1, "MongoDB\nresults, users, alerts", w=1.9, fill=GOLD, edge=INK)
    d.entity("sources", 1.2, 3.1, "NASA, NOAA,\nOpenAQ files")
    d.box("hdfs", 3.9, 3.1, "HDFS\nraw and processed data", fill=GOLD, edge=INK)
    d.box("yarn", 6.6, 3.65, "MapReduce on YARN\n5 Python streaming jobs")
    d.entity("meteo", 1.2, 1.5, "Open-Meteo\nlive feed")
    d.box("collector", 3.9, 1.5, "Collector service\nevery 15 minutes")
    d.box("ml", 6.6, 1.0, "Model training\nscikit-learn, statsmodels")
    d.box("ops", 8.9, 1.0, "Backup and\nhealth monitor", w=1.9)
    d.arrow("user", "apache", "HTTPS")
    d.arrow("apache", "a", "HTTP", offset=(-.1, .28))
    d.arrow("apache", "b", offset=(0, 0))
    d.arrow("a", "mongo", start=(7.65, 5.7), end=(9.3, 3.45), bend=-.25)
    d.arrow("b", "mongo", start=(7.65, 4.9), end=(8.6, 3.45), bend=-.15)
    d.arrow("sources", "hdfs", "download")
    d.arrow("hdfs", "yarn", "raw", offset=(-.05, .15))
    d.arrow("yarn", "mongo", "results", start=(7.65, 3.65), end=(7.95, 3.3), offset=(.12, .22))
    d.arrow("meteo", "collector", "API")
    d.arrow("collector", "hdfs", "hourly CSV")
    d.arrow("collector", "mongo", "readings, alerts", start=(4.95, 1.6), end=(7.95, 2.95), offset=(-.2, .2))
    d.arrow("mongo", "ml", "history", start=(8.2, 2.75), end=(7.1, 1.35), offset=(-.2, .1))
    d.arrow("ml", "mongo", "scores", start=(7.5, 1.35), end=(8.6, 2.75), offset=(.3, -.1))
    d.arrow("ops", "mongo", "dump, checks", start=(9.2, 1.35), end=(9.2, 2.75), offset=(.15, 0))
    d.save("architecture")


def dfd_level0():
    d = Diagram(10, 5, "Data flow diagram, level 0 (context)")
    d.process("system", 5, 2.3, "EarthScape\nClimate Platform", r=1.15)
    d.entity("admin", 1.3, 3.7, "Administrator")
    d.entity("analyst", 1.3, 1.0, "Analyst")
    d.entity("sources", 8.7, 3.7, "Climate data\nsources")
    d.entity("mail", 8.7, 1.0, "Mail server")
    d.arrow("admin", "system", "datasets, rules, users,\nretrain and job requests", bend=-.08, offset=(.05, .35))
    d.arrow("system", "admin", "status, results", bend=-.12, offset=(-.1, -.35))
    d.arrow("analyst", "system", "queries, tickets,\nalert updates", bend=.08, offset=(.05, -.35))
    d.arrow("system", "analyst", "charts, reports,\nforecasts, alerts", bend=.12, offset=(-.1, .35))
    d.arrow("sources", "system", "historical files,\nlive readings", offset=(0, .25))
    d.arrow("system", "mail", "alert emails", offset=(0, -.2))
    d.save("dfd_level0")


def dfd_level1():
    d = Diagram(11, 7.4, "Data flow diagram, level 1")
    d.entity("sources", 1.3, 6.2, "Climate data\nsources")
    d.entity("feed", 1.3, 3.9, "Open-Meteo")
    d.entity("user", 9.7, 6.2, "Admin / Analyst")
    d.entity("mail", 9.7, 1.0, "Mail server")
    d.process("p1", 3.9, 6.2, "1.0 Ingest\nfiles")
    d.process("p2", 6.6, 6.2, "2.0 Process\nMapReduce")
    d.process("p3", 3.9, 3.9, "3.0 Collect\nlive data")
    d.process("p4", 3.9, 1.5, "4.0 Train\nmodels")
    d.process("p5", 9.7, 3.9, "5.0 Serve API\nand dashboard")
    d.process("p6", 6.6, 1.5, "6.0 Check rules\nand notify")
    d.store("hdfs", 5.25, 5.0, "D1 HDFS")
    d.store("mongo", 6.8, 3.9, "D2 MongoDB", w=2.2)
    d.arrow("sources", "p1", "raw files")
    d.arrow("p1", "hdfs", offset=(0, 0))
    d.arrow("hdfs", "p2", "raw records", offset=(.25, -.1))
    d.arrow("p2", "mongo", "summaries,\nanomalies", offset=(.45, .1))
    d.arrow("feed", "p3", "current readings")
    d.arrow("p3", "hdfs", "hourly batches", offset=(-.55, .08))
    d.arrow("p3", "mongo", "readings")
    d.arrow("mongo", "p4", "history", offset=(-.25, .15))
    d.arrow("p4", "mongo", "forecasts, scores", bend=.25, offset=(.7, -.3))
    d.arrow("mongo", "p6", "latest values", bend=-.2, offset=(-.45, .1))
    d.arrow("p6", "mongo", "alerts", bend=-.2, offset=(.4, 0))
    d.arrow("p6", "mail", "alert emails")
    d.arrow("mongo", "p5", "results", bend=-.12, offset=(0, -.28))
    d.arrow("p5", "mongo", "users, rules, tickets", bend=-.12, offset=(0, .28))
    d.arrow("user", "p5", "requests", bend=.2, offset=(.42, 0))
    d.arrow("p5", "user", "pages, reports", bend=.2, offset=(-.55, 0))
    d.save("dfd_level1")


def flow_sign_in():
    d = Diagram(7.4, 8.2, "Flowchart: sign-in")
    d.start("s", 3.0, 7.3, "Start")
    d.box("enter", 3.0, 6.45, "Enter email and password")
    d.decision("limit", 3.0, 5.4, "Too many recent\nfailures?")
    d.box("block", 6.1, 5.4, "Answer 429:\ntry again later")
    d.box("find", 3.0, 4.35, "Find user by email lookup\nand compare bcrypt hash", w=2.5)
    d.decision("ok", 3.0, 3.3, "Correct and\naccount active?")
    d.box("fail", 6.1, 3.3, "Count the failure,\nanswer 401")
    d.box("token", 3.0, 2.2, "Clear failures, issue\n8-hour signed token")
    d.box("dash", 3.0, 1.35, "Open dashboard for the role", w=2.5)
    d.start("e", 3.0, .55, "End")
    for a, b in [("s", "enter"), ("enter", "limit"), ("find", "ok"), ("token", "dash"), ("dash", "e")]:
        d.arrow(a, b)
    d.arrow("limit", "find", "No", offset=(.25, 0))
    d.arrow("limit", "block", "Yes", offset=(0, .12))
    d.arrow("ok", "token", "Yes", offset=(.25, 0))
    d.arrow("ok", "fail", "No", offset=(0, .12))
    d.save("flow_sign_in")


def flow_pipeline():
    d = Diagram(7.4, 8.6, "Flowchart: batch pipeline")
    d.start("s", 3.0, 7.75, "Start")
    d.box("get", 3.0, 6.95, "Download public datasets to data/raw", w=3.2)
    d.box("load", 3.0, 6.15, "Load files into HDFS,\nfoldered by source and year", w=3.2)
    d.box("job", 3.0, 5.3, "Submit next MapReduce job to YARN", w=3.2)
    d.box("map", 3.0, 4.5, "Map: parse, reject bad records, key each row", w=3.6)
    d.box("red", 3.0, 3.7, "Reduce: combine by key, write to HDFS", w=3.2)
    d.decision("more", 3.0, 2.75, "More jobs?", h=.8, w=2)
    d.box("mongo", 3.0, 1.85, "Copy results into MongoDB, save run times", w=3.6)
    d.box("show", 3.0, 1.1, "Dashboard shows the new results", w=3.2, h=.55)
    d.start("e", 3.0, .4, "End", h=.42)
    for a, b in [("s", "get"), ("get", "load"), ("load", "job"), ("job", "map"), ("map", "red"), ("red", "more"), ("mongo", "show"), ("show", "e")]:
        d.arrow(a, b)
    d.arrow("more", "mongo", "No", offset=(.25, 0))
    d.box("loop", 6.1, 2.75, "Yes: next job", w=1.5, h=.5, fill="#ffffff")
    d.arrow("more", "loop")
    d.axes.annotate("", xy=(4.6, 5.3), xytext=(6.1, 3.0), arrowprops=dict(arrowstyle="-|>", color=INK, linewidth=1, connectionstyle="angle,angleA=90,angleB=0,rad=3"), zorder=2)
    d.save("flow_pipeline")


def flow_live():
    d = Diagram(7.4, 8.2, "Flowchart: live collection and alerts")
    d.start("s", 3.0, 7.3, "Every 15 minutes")
    d.box("get", 3.0, 6.45, "Fetch weather and air quality\nfor 12 cities", w=2.8)
    d.decision("ok", 3.0, 5.4, "Fetch worked?")
    d.box("log", 6.1, 5.4, "Record the failed poll;\nshow data as stale")
    d.box("store", 3.0, 4.4, "Store readings, skip duplicates", w=2.8)
    d.box("check", 3.0, 3.6, "Compare latest values with each rule", w=3.1)
    d.decision("over", 3.0, 2.65, "Above the limit?", h=.85)
    d.box("close", 6.1, 2.65, "Close any open alert\nfor that rule and place")
    d.box("alert", 3.0, 1.65, "Open alert, notify in the app,\nsend email if configured", w=2.8)
    d.start("e", 3.0, .75, "Wait for next poll", w=2.1)
    for a, b in [("s", "get"), ("get", "ok"), ("store", "check"), ("check", "over"), ("alert", "e")]:
        d.arrow(a, b)
    d.arrow("ok", "store", "Yes", offset=(.25, 0))
    d.arrow("ok", "log", "No", offset=(0, .12))
    d.arrow("over", "alert", "Yes", offset=(.25, 0))
    d.arrow("over", "close", "No", offset=(0, .12))
    d.save("flow_live")


def flow_training():
    d = Diagram(7.4, 7.4, "Flowchart: model training")
    d.start("s", 3.0, 6.5, "Admin clicks Retrain")
    d.decision("lock", 3.0, 5.5, "Already running?")
    d.box("busy", 6.1, 5.5, "Answer 409")
    d.box("read", 3.0, 4.5, "Read history from MongoDB and files", w=3.0)
    d.box("back", 3.0, 3.7, "Backtest forecast methods on past data", w=3.3)
    d.box("test", 3.0, 2.9, "Score the winner once on the last 10 years", w=3.5)
    d.box("iso", 3.0, 2.1, "Fit Isolation Forest, compute correlations", w=3.5)
    d.box("save", 3.0, 1.3, "Save scores, forecasts and model files", w=3.5)
    d.start("e", 3.0, .5, "Dashboard updates", w=2)
    for a, b in [("s", "lock"), ("read", "back"), ("back", "test"), ("test", "iso"), ("iso", "save"), ("save", "e")]:
        d.arrow(a, b)
    d.arrow("lock", "read", "No", offset=(.25, 0))
    d.arrow("lock", "busy", "Yes", offset=(0, .12))
    d.save("flow_training")


def data_model():
    d = Diagram(10, 4.8, "Main MongoDB collections")
    columns = [
        ("Accounts and support", ["users", "tickets", "notifications", "revoked_tokens", "login_failures"]),
        ("Pipeline results", ["gistemp_global, gistemp_zonal", "co2_annual, data_quality", "regional_monthly, satellite_zonal", "air_quality_monthly", "station_anomalies"]),
        ("Models and live data", ["ml_runs, ml_forecasts", "ml_anomalies, ml_correlations", "live_readings, live_polls", "live_batches", "alert_rules, alerts"]),
        ("Operations", ["pipeline_runs", "health_checks", "backups", "locks", "settings"]),
    ]
    for index, (title, names) in enumerate(columns):
        x = 1.25 + index * 2.5
        d.box("title%d" % index, x, 3.75, title, w=2.35, h=.55, fill=DARK, color="#ffffff", edge=DARK)
        for row, name in enumerate(names):
            d.box("%d-%d" % (index, row), x, 3.05 - row * .63, name, w=2.35, h=.55, fill=PALE if index % 2 == 0 else GREY)
    d.save("data_model")


if __name__ == "__main__":
    for draw in (architecture, dfd_level0, dfd_level1, flow_sign_in, flow_pipeline, flow_live, flow_training, data_model):
        draw()
    print("Done:", HERE)
