#!/usr/bin/env python3
"""Early Careers Board: recolecta stages, alternances, junior/graduate y VIE.

  python scraper/jobboard.py            # recoge ofertas y escribe docs/jobs.json
  python scraper/jobboard.py --detect   # solo prueba qué ATS usa cada empresa
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "companies.yaml"
CACHE = ROOT / "ats_cache.json"
OUT = ROOT / "docs" / "jobs.json"
NEW_OUT = ROOT / "docs" / "new_jobs.json"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; EarlyCareersBoard/1.0)",
    "Accept": "application/json",
})


class NotFound(Exception):
    pass


def http(method: str, url: str, **kw):
    kw.setdefault("timeout", 25)
    for attempt in range(3):
        try:
            r = SESSION.request(method, url, **kw)
        except requests.RequestException:
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError:
                raise NotFound(f"no-json {url}")
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 * (attempt + 1))
            continue
        raise NotFound(f"{r.status_code} {url}")
    raise NotFound(f"unreachable {url}")


# --------------------------------------------------------------- fechas
def iso_date(value) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(value))
    return m.group(1) if m else None


def relative_date(text: str) -> str | None:
    t = (text or "").lower()
    today = datetime.now(timezone.utc).date()
    if "today" in t:
        return today.isoformat()
    if "yesterday" in t:
        return (today - timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\+?\s*day", t)
    if m:
        return (today - timedelta(days=int(m.group(1)))).isoformat()
    return None


# ----------------------------------------------------------- conectores
# Cada conector devuelve: [{title, location, url, posted, extra}]
def greenhouse(slug, **_):
    data = http("GET", f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    return [{
        "title": j.get("title", ""),
        "location": (j.get("location") or {}).get("name", ""),
        "url": j.get("absolute_url", ""),
        "posted": iso_date(j.get("first_published") or j.get("updated_at")),
        "extra": "",
    } for j in data.get("jobs", [])]


def lever(slug, **_):
    last = None
    for host in ("api.lever.co", "api.eu.lever.co"):
        try:
            data = http("GET", f"https://{host}/v0/postings/{slug}", params={"mode": "json"})
        except NotFound as e:
            last = e
            continue
        out = []
        for j in data:
            c = j.get("categories") or {}
            out.append({
                "title": j.get("text", ""),
                "location": c.get("location") or " / ".join(c.get("allLocations") or []),
                "url": j.get("hostedUrl", ""),
                "posted": iso_date(j.get("createdAt")),
                "extra": c.get("commitment") or "",
            })
        return out
    raise last or NotFound(slug)


def ashby(slug, **_):
    data = http("GET", f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""]
        locs += [s.get("location", "") for s in j.get("secondaryLocations", []) if isinstance(s, dict)]
        out.append({
            "title": j.get("title", ""),
            "location": " / ".join(x for x in locs if x),
            "url": j.get("jobUrl", ""),
            "posted": iso_date(j.get("publishedAt")),
            "extra": j.get("employmentType") or "",
        })
    return out


def smartrecruiters(slug, **_):
    out, offset = [], 0
    while offset < 2000:
        data = http("GET", f"https://api.smartrecruiters.com/v1/companies/{slug}/postings",
                    params={"limit": 100, "offset": offset})
        items = data.get("content", [])
        for j in items:
            loc = j.get("location") or {}
            location = ", ".join(x for x in [loc.get("city"), (loc.get("country") or "").upper()] if x)
            toe = (j.get("typeOfEmployment") or {}).get("label", "")
            exp = (j.get("experienceLevel") or {}).get("label", "")
            out.append({
                "title": j.get("name", ""),
                "location": location,
                "url": f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}",
                "posted": iso_date(j.get("releasedDate")),
                "extra": f"{toe} {exp}".strip(),
            })
        offset += 100
        if len(items) < 100 or offset >= data.get("totalFound", 0):
            break
    return out


def recruitee(slug, **_):
    data = http("GET", f"https://{slug}.recruitee.com/api/offers/")
    return [{
        "title": j.get("title", ""),
        "location": ", ".join(x for x in [j.get("city"), (j.get("country_code") or "").upper()] if x),
        "url": j.get("careers_url", ""),
        "posted": iso_date(j.get("published_at") or j.get("created_at")),
        "extra": j.get("employment_type_code") or "",
    } for j in data.get("offers", [])]


def workable(slug, **_):
    out, token = [], None
    for _page in range(30):
        body = {"query": "", "location": [], "department": [], "worktype": [], "remote": []}
        if token:
            body["token"] = token
        data = http("POST", f"https://apply.workable.com/api/v3/accounts/{slug}/jobs", json=body)
        for j in data.get("results", []):
            loc = j.get("location") or {}
            out.append({
                "title": j.get("title", ""),
                "location": ", ".join(x for x in [loc.get("city"), loc.get("country")] if x),
                "url": f"https://apply.workable.com/{slug}/j/{j.get('shortcode')}/",
                "posted": iso_date(j.get("published")),
                "extra": j.get("employment_type") or "",
            })
        token = data.get("nextPage")
        if not token:
            break
    return out


WORKDAY_TERMS = ["intern", "stage", "alternance", "graduate", "junior", "apprentice",
                 "praktikum", "werkstudent", "trainee", "V.I.E", "lehre", "lernende", "postgraduate"]


def workday(slug=None, host=None, tenant=None, site=None, **_):
    if not (host and tenant and site):
        raise NotFound("workday necesita host, tenant y site")
    seen, out = set(), []
    for term in WORKDAY_TERMS:
        for page in range(40):
            data = http("POST", f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
                        json={"appliedFacets": {}, "limit": 20, "offset": page * 20, "searchText": term})
            posts = data.get("jobPostings", [])
            for j in posts:
                path = j.get("externalPath", "")
                if path in seen:
                    continue
                seen.add(path)
                out.append({
                    "title": j.get("title", ""),
                    "location": (" ".join(path.split("/")[2:3]).replace("-", " ") if re.search(r"(?i)locations?|ubicaciones", j.get("locationsText", "")) else j.get("locationsText", "")), "hint": " ".join(path.split("/")[2:3]).replace("-", " "),
                    "url": f"https://{host}/en-US/{site}{path}",
                    "posted": relative_date(j.get("postedOn", "")),
                    "extra": "",
                })
            if len(posts) < 20:
                break
    return out


CONNECTORS = {
    "greenhouse": greenhouse, "lever": lever, "ashby": ashby,
    "smartrecruiters": smartrecruiters, "recruitee": recruitee,
    "workable": workable, "workday": workday,
}
PROBE_ORDER = ["greenhouse", "lever", "ashby", "smartrecruiters", "recruitee", "workable"]

# --------------------------------------------------------- clasificación
RE_APPR = re.compile(
    r"\b(alternance|alternant(?:e)?|apprenti(?:e)?|apprentissage|apprenticeship|apprentice|"
    r"ausbildung|auszubildende(?:r)?|azubi|lehre|lernende(?:r)?|lehrling|duales? studium|dual student|duales? bachelor|"
    r"work[- ]study|contrat pro(?:fessionnalisation)?)\b", re.I)
RE_INTERN = re.compile(
    r"\b(interns?|internships?|stages?|stagiaires?|praktikum|praktikant(?:in)?|pflichtpraktikum|"
    r"werkstudent(?:in)?|werkstudium|pasante|pr[aá]cticas|placement student|summer student|co-?op|"
    r"abschlussarbeit|bachelorarbeit|masterarbeit)\b", re.I)
RE_GRAD = re.compile(
    r"\b(graduates?|postgraduate|next generation scientist|new grad|junior|jr\.?|entry[- ]level|early careers?|trainee|"
    r"jeune dipl[oô]m[eé]|d[eé]butant(?:e)?|berufseinsteiger(?:in)?|absolvent(?:en)?|einsteiger|"
    r"young professional|rotational|analyst program)\b", re.I)
RE_SENIOR = re.compile(
    r"\b(senior|sr\.?|lead|principal|staff|head of|director|vp|vice president|chief|expert|architect)\b", re.I)


def classify(title: str, extra: str = "") -> str | None:
    text = f"{title} {extra}".strip()
    if RE_APPR.search(text):
        return "alternance"
    # "VIE" solo en mayúsculas (sigla): en minúsculas sería la palabra francesa "vie"
    if re.search(r"\bV\.?I\.?E\b", title) or re.search(r"volontariat international", text, re.I):
        return "vie"
    if RE_INTERN.search(text):
        return "stage"
    if RE_GRAD.search(text) and not RE_SENIOR.search(title):
        return "junior"
    return None


COUNTRY_WORDS = {
    "FR": ["france", "paris", "lyon", "marseille", "toulouse", "lille", "bordeaux", "nantes",
           "strasbourg", "nice", "grenoble", "rennes", "montpellier", "île-de-france",
           "ile-de-france", "la défense", "la defense", "courbevoie", "puteaux", "nanterre",
           "gennevilliers", "saint-denis", "boulogne-billancourt", "issy-les-moulineaux",
           "marcy-l'étoile", "marcy l'etoile", "sophia antipolis", "levallois"],
    "DE": ["germany", "deutschland", "berlin", "munich", "münchen", "munchen", "frankfurt",
           "hamburg", "cologne", "köln", "stuttgart", "düsseldorf", "dusseldorf", "erlangen",
           "karlsruhe", "walldorf", "dresden", "leipzig", "nürnberg", "nuremberg", "bonn",
           "hannover", "mannheim", "heidelberg", "bremen", "eschborn", "darmstadt"],
    "CH": ["switzerland", "schweiz", "suisse", "svizzera", "zurich", "zürich", "geneva",
           "genève", "geneve", "genf", "basel", "bern", "lausanne", "zug", "lugano", "lucerne",
           "luzern", "winterthur", "schlieren", "kaiseraugst", "stäfa", "stafa", "neuchâtel",
           "allschwil", "baar", "rotkreuz", "kloten", "wallisellen"],
    "IE": ["ireland", "dublin", "cork", "galway", "limerick", "waterford", "athlone",
           "kilkenny", "leixlip", "sligo", "ennis", "clonmel", "tullamore"],
    "LU": ["luxembourg", "luxemburg", "esch-sur-alzette", "betzdorf", "kirchberg",
           "leudelange", "bertrange", "strassen", "munsbach", "howald", "findel", "belval"],
}
COUNTRY_RES = {c: re.compile(r"(?<![a-zà-ÿ])(" + "|".join(re.escape(w) for w in ws) + r")(?![a-zà-ÿ])")
               for c, ws in COUNTRY_WORDS.items()}
CODE_RE = re.compile(r"(?:^|[,\-(/|]\s*)(FR|DE|CH|IE|LU)(?:\s*$|\s*[,)\-/|])")
ISO3 = {"FRA": "FR", "DEU": "DE", "CHE": "CH", "IRL": "IE", "LUX": "LU"}


def detect_countries(location: str) -> set[str]:
    found = set()
    low = (location or "").lower()
    for code, rx in COUNTRY_RES.items():
        if rx.search(low):
            found.add(code)
    for m in CODE_RE.finditer(location or ""):
        found.add(m.group(1))
    for tok in re.findall(r"\b[A-Z]{3}\b", location or ""):
        if tok in ISO3:
            found.add(ISO3[tok])
    return found


# ------------------------------------------------------------- pipeline
def slug_candidates(name: str, hints) -> list[str]:
    norm = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    words = re.findall(r"[a-z0-9]+", norm)
    cands = list(hints or []) + ["".join(words), "-".join(words)]
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def resolve(company: dict, cache: dict, connectors=None, force=False):
    """Devuelve (ats, kwargs) o None si no hay API pública detectada."""
    connectors = connectors or CONNECTORS
    name = company["name"]
    if company.get("ats") in connectors:
        kw = {k: company[k] for k in ("slug", "host", "tenant", "site") if k in company}
        return company["ats"], kw
    hit = cache.get(name)
    today = datetime.now(timezone.utc).date()
    if hit and hit.get("ats") and not force:
        return hit["ats"], {"slug": hit["slug"]}
    if hit and not hit.get("ats") and not force:
        checked = datetime.fromisoformat(hit["checked"]).date()
        if (today - checked).days < 7:
            return None
    for slug in slug_candidates(name, company.get("slugs")):
        for ats in PROBE_ORDER:
            try:
                jobs = connectors[ats](slug=slug)
            except Exception:
                continue
            if jobs:
                cache[name] = {"ats": ats, "slug": slug}
                return ats, {"slug": slug}
    cache[name] = {"ats": None, "checked": today.isoformat()}
    return None


def make_id(company: str, title: str, loc: str) -> str:
    key = f"{company}|{title}|{loc}".lower()
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def collect(config: dict, cache: dict, prev_jobs: list[dict], connectors=None, log=print, pause=0.3):
    connectors = connectors or CONNECTORS
    wanted = set(config.get("countries", ["FR", "DE", "CH", "IE", "LU"]))
    prev_by_company: dict[str, list[dict]] = {}
    for j in prev_jobs:
        prev_by_company.setdefault(j["company"], []).append(j)
    prev_first_seen = {j["id"]: j.get("first_seen") for j in prev_jobs}
    today = datetime.now(timezone.utc).date().isoformat()

    jobs, companies, seen_ids = [], [], set()
    for c in config["companies"]:
        name = c["name"]
        info = {"name": name, "sector": c.get("sector", ""), "ats": None, "jobs": 0, "error": None,
                "search_url": "https://www.google.com/search?q=" + quote(
                    f"{name} early careers graduate internship alternance")}
        res = resolve(c, cache, connectors)
        if not res:
            companies.append(info)
            log(f"  - {name}: sin API pública conocida")
            continue
        ats, kw = res
        info["ats"] = ats
        try:
            raw = connectors[ats](**kw)
            mine = []
            for r in raw:
                kind = classify(r["title"], r.get("extra", ""))
                if not kind or (r.get("posted") and r["posted"] < (datetime.now(timezone.utc).date() - timedelta(days=180)).isoformat()):
                    continue
                ctry = detect_countries(r["location"] + " " + r.get("hint", ""))
                if not (ctry & wanted):
                    continue
                jid = make_id(name, r["title"], r["location"])
                if jid in seen_ids:
                    continue
                seen_ids.add(jid)
                mine.append({
                    "id": jid, "title": r["title"].strip(), "company": name,
                    "sector": c.get("sector", ""), "location": r["location"],
                    "countries": sorted(ctry & wanted), "type": kind, "url": r["url"],
                    "posted": r.get("posted"), "first_seen": prev_first_seen.get(jid) or today,
                    "source": ats,
                })
            jobs.extend(mine)
            info["jobs"] = len(mine)
            log(f"  ✓ {name} ({ats}): {len(raw)} ofertas leídas, {len(mine)} relevantes")
        except Exception as e:  # una empresa rota no debe parar el resto
            info["error"] = str(e)[:200]
            kept = [j for j in prev_by_company.get(name, []) if j["id"] not in seen_ids]
            for j in kept:
                seen_ids.add(j["id"])
            jobs.extend(kept)
            info["jobs"] = len(kept)
            log(f"  ✗ {name} ({ats}): {e} -> se conservan {len(kept)} ofertas anteriores")
        companies.append(info)
        time.sleep(pause)

    jobs.sort(key=lambda j: (j.get("posted") or "0000", j.get("first_seen") or ""), reverse=True)
    return jobs, companies


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--detect", action="store_true", help="solo detectar el ATS de cada empresa")
    args = ap.parse_args()
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    cache = load_json(CACHE, {})

    if args.detect:
        print("Detectando ATS (comprueba que las ofertas de ejemplo son de la empresa correcta):")
        for c in config["companies"]:
            cache.pop(c["name"], None)
            res = resolve(c, cache, force=True)
            if not res:
                print(f"  ✗ {c['name']}: no detectado (añade slugs/ats en companies.yaml o déjalo en el directorio)")
                continue
            ats, kw = res
            sample = CONNECTORS[ats](**kw)[:1]
            ex = f"{sample[0]['title']} -> {sample[0]['url']}" if sample else "sin ofertas"
            print(f"  ✓ {c['name']}: {ats} / {kw.get('slug')}  |  {ex}")
        CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
        return

    prev = load_json(OUT, {}).get("jobs", [])
    print("Recolectando ofertas...")
    jobs, companies = collect(config, cache, prev)
    prev_ids = {j["id"] for j in prev}
    new = [j for j in jobs if j["id"] not in prev_ids] if prev else []
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({
        "updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "count": len(jobs), "jobs": jobs, "companies": companies,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    NEW_OUT.write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")
    CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\n{len(jobs)} ofertas en total, {len(new)} nuevas.")


if __name__ == "__main__":
    main()
