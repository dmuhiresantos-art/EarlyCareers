"""Pruebas sin red: clasificación, países y pipeline con conectores falsos."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scraper"))
import jobboard as jb

CLASSIFY = [
    ("Stage - Business Developer H/F", "", "stage"),
    ("Software Engineering Intern", "", "stage"),
    ("Praktikum Data Science (m/w/d)", "", "stage"),
    ("Werkstudent Marketing", "", "stage"),
    ("Alternance Chargé de communication", "", "alternance"),
    ("Apprenti Ingénieur Logiciel", "", "alternance"),
    ("Ausbildung zum Fachinformatiker", "", "alternance"),
    ("V.I.E Business Analyst - Singapore", "", "vie"),
    ("Mission VIE Contrôleur de gestion", "", "vie"),
    ("Graduate Program Finance", "", "junior"),
    ("Junior Data Analyst", "", "junior"),
    ("Software Engineer", "Entry Level", "junior"),
    ("Senior Software Engineer", "", None),
    ("Junior Lead Architect", "", None),
    ("Ma vie en entreprise Manager", "", None),
    ("Internal Auditor", "", None),
    ("International Sales Director", "", None),
    ("Account Executive", "Full-time", None),
]
for title, extra, want in CLASSIFY:
    got = jb.classify(title, extra)
    assert got == want, (title, extra, got, want)

COUNTRIES = [
    ("Paris, France", {"FR"}), ("Dublin, Ireland", {"IE"}), ("Zürich", {"CH"}),
    ("Berlin, DE", {"DE"}), ("Luxembourg", {"LU"}), ("Munich or Paris", {"DE", "FR"}),
    ("Île de France", {"FR"}), ("New York, NY", set()), ("Remote", set()),
    ("Cork, IE", {"IE"}), ("Esch-sur-Alzette, LU", {"LU"}), ("Singapore", set()),
    ("Paris, FRA", {"FR"}),
]
for loc, want in COUNTRIES:
    got = jb.detect_countries(loc)
    assert got == want, (loc, got, want)

def fake_a(slug=None, **_):
    if slug and slug.startswith("ghost"):
        raise jb.NotFound("404")
    return [
        {"title": "Stage Data", "location": "Paris, France", "url": "https://x/1", "posted": "2026-10-20", "extra": ""},
        {"title": "Stage Data", "location": "Paris, France", "url": "https://x/1b", "posted": "2026-10-20", "extra": ""},  # duplicado
        {"title": "Senior Dev", "location": "Paris, France", "url": "https://x/2", "posted": "2026-10-21", "extra": ""},
        {"title": "Intern", "location": "Austin, TX", "url": "https://x/3", "posted": "2026-10-22", "extra": ""},
        {"title": "Graduate Analyst", "location": "Dublin, Ireland", "url": "https://x/4", "posted": "2026-10-25", "extra": ""},
    ]

def fake_broken(slug=None, **_):
    raise jb.NotFound("500")

conn = {"greenhouse": fake_a, "lever": fake_broken, "ashby": fake_broken, "smartrecruiters": fake_broken,
        "recruitee": fake_broken, "workable": fake_broken, "workday": fake_broken}
cfg = {"countries": ["FR", "IE"], "companies": [
    {"name": "Acme", "sector": "tech"},
    {"name": "Ghost Corp", "sector": "finance"},
    {"name": "Broken Inc", "sector": "tech", "ats": "workday", "host": "h", "tenant": "t", "site": "s"},
]}
prev = [{"id": "old1", "title": "Stage Old", "company": "Broken Inc", "first_seen": "2026-10-01"}]
cache = {}
jobs, companies = jb.collect(cfg, cache, prev, connectors=conn, log=lambda *_: None, pause=0)
titles = [(j["company"], j["title"]) for j in jobs]
assert ("Acme", "Stage Data") in titles and ("Acme", "Graduate Analyst") in titles, titles
assert len([t for t in titles if t == ("Acme", "Stage Data")]) == 1          # deduplicado
assert not any(t[1] in ("Senior Dev", "Intern") for t in titles if t[0] == "Acme")  # filtros
assert ("Broken Inc", "Stage Old") in titles                                  # conserva lo anterior si falla
assert cache["Acme"] == {"ats": "greenhouse", "slug": "acme"}
assert cache["Ghost Corp"]["ats"] is None
assert jobs[0]["title"] == "Graduate Analyst"                                 # orden por fecha
by = {c["name"]: c for c in companies}
assert by["Ghost Corp"]["ats"] is None and by["Broken Inc"]["error"]
print("OK: todas las pruebas offline pasan")
