#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mss_update.py  —  Klementmodellen / "Oscars funderingar"  ·  VM 2026

Räknar fram Model Strength Score (MSS, 0–100) för alla 48 lag enligt den
DATADRIVNA VÄGEN som beskrivs på Källor & Metod-sidan:

    MSS = 0.38·Ranking + 0.22·Talang + 0.16·Form + 0.12·Meriter
        + 0.07·Kultur + 0.05·Socioekonomi          ( ± kontext )

  • Ranking (38%)  ← World Football Elo Ratings (eloratings.net), min–max-skalad
  • Form    (16%)  ← Elo-delta (nu − för 12 mån sedan), symmetriskt runt 50
  • Talang  (22%)  ← CIES Football Observatory, truppvärde i € → log → min–max
  • Meriter (12%)  ← omdöme/historik (RSSSF, FIFA), 0–100   } läses från
  • Kultur   (7%)  ← ligakoefficienter (UEFA/IFFHS), 0–100   } redigerbar
  • Socioek. (5%)  ← Världsbanken, BNP/capita × bef → 0–100   } konfig (JSON)

Elo (Ranking + Form) hämtas live. Talang (CIES) och de tre omdömesfaktorerna
läses från mss_input.json. Resultatet skrivs till mss.json.

ANVÄNDNING
  python3 mss_update.py --selftest      # ingen nät — kör med inbäddad exempeldata
  python3 mss_update.py --init          # skriver mss_input.example.json att fylla i
  python3 mss_update.py                  # skarp körning: hämtar Elo live + läser mss_input.json

Endast Python-standardbibliotek. Samma anda som facit_update.py:
en självtest som kör utan nät, en skarp körning som hämtar live.
"""

import argparse
import json
import math
import sys
import io
import csv
import urllib.request
import urllib.error

# ----------------------------------------------------------------------------
# VIKTER (måste summera till 1.0)
# ----------------------------------------------------------------------------
WEIGHTS = {"R": 0.38, "T": 0.22, "F": 0.16, "M": 0.12, "K": 0.07, "S": 0.05}

# ----------------------------------------------------------------------------
# ELO-KÄLLA (eloratings.net)
#   OBS: eloratings.net är en tunn SPA ovanpå TSV-filer. Sökvägen kan ändras —
#   verifiera aktuell endpoint i webbläsarens nätverksflik om hämtningen failar.
#   "World"-filen = aktuella ratingar; årsfil (t.ex. 2025) = årsslut, för delta.
#   Parsern är heuristisk: den letar reda på lagnamn + en rating i rimligt
#   Elo-spann (1000–2400), så den är tålig mot exakt kolumnordning.
# ----------------------------------------------------------------------------
ELO_NOW_URL = "https://www.eloratings.net/World.tsv"
ELO_PREV_URL_TEMPLATE = "https://www.eloratings.net/{year}.tsv"
ELO_MIN, ELO_MAX = 1000.0, 2400.0  # rimlighetsfönster för rating-kolumnen

# ----------------------------------------------------------------------------
# DE 48 LAGEN  (VM 2026, 12 grupper A–L)
#   Fält per rad:
#     sv          svenskt namn (för utskrift)
#     en          engelskt namn
#     elo         lagnamn så som det skrivs på eloratings.net (för matchning)
#     elo_now     ⟵ SJÄLVTEST-frö: ungefärlig Elo nu (riktig topp ~jan 2026)
#     d12         ⟵ SJÄLVTEST-frö: Elo-förändring senaste 12 mån (+ = stigande)
#     cies        ⟵ SJÄLVTEST-frö: ungefärligt truppvärde i miljoner €
#     M, K, S     ⟵ SJÄLVTEST-frö: omdömes-/historikpoäng 0–100
#     ctx         ⟵ SJÄLVTEST-frö: kontextnudge i MSS-poäng (hemmaplan/höjd/skador)
#
#   Vid skarp körning ersätts elo_now/elo_prev av LIVE-data från eloratings.net,
#   och cies/M/K/S/ctx läses från mss_input.json. Siffrorna här är alltså bara
#   illustrativa frön så att --selftest kan köra hela kedjan utan nät.
# ----------------------------------------------------------------------------
#        sv,               en,              elo (eloratings.net),  elo_now, d12, cies,  M,  K,  S, ctx
TEAMS = [
    # Grupp A
    ("Mexiko",          "Mexico",          "Mexico",                1880,  10,  320, 55, 60, 62,  2.0),
    ("Sydkorea",        "South Korea",     "South Korea",           1820,  15,  300, 45, 58, 58,  0.0),
    ("Tjeckien",        "Czechia",         "Czechia",               1760, -10,  200, 45, 62, 40,  0.0),
    ("Sydafrika",       "South Africa",    "South Africa",          1620,  20,   70, 30, 40, 40,  0.0),
    # Grupp B
    ("Kanada",          "Canada",          "Canada",                1800,  20,  240, 25, 55, 55,  1.5),
    ("Schweiz",         "Switzerland",     "Switzerland",           1897,  30,  380, 60, 66, 58,  0.0),
    ("Qatar",           "Qatar",           "Qatar",                 1650, -30,   60, 30, 35, 60,  0.0),
    ("Bosnien",         "Bosnia & H.",     "Bosnia and Herzegovina",1700,  10,  150, 35, 50, 30,  0.0),
    # Grupp C
    ("Brasilien",       "Brazil",          "Brazil",                1979, -15, 1050,100, 85, 70, -1.0),
    ("Marocko",         "Morocco",         "Morocco",               1850,  20,  420, 50, 60, 45,  0.0),
    ("Skottland",       "Scotland",        "Scotland",              1780,  10,  180, 35, 70, 50,  0.0),
    ("Haiti",           "Haiti",           "Haiti",                 1520,   5,   50, 20, 25, 20,  0.0),
    # Grupp D
    ("USA",             "USA",             "United States",         1820,  10,  360, 45, 55,100,  2.0),
    ("Paraguay",        "Paraguay",        "Paraguay",              1730,  15,  120, 45, 50, 40,  0.0),
    ("Australien",      "Australia",       "Australia",             1720,  10,   90, 40, 55, 60,  0.0),
    ("Turkiet",         "Türkiye",         "Turkey",                1880,  55,  420, 50, 62, 55,  0.0),
    # Grupp E
    ("Tyskland",        "Germany",         "Germany",               1910, -10, 1000, 95, 90, 88,  0.0),
    ("Ecuador",         "Ecuador",         "Ecuador",               1933,  20,  380, 40, 52, 45,  0.0),
    ("Elfenbenskusten", "Ivory Coast",     "Ivory Coast",           1750,  10,  260, 45, 50, 40,  0.0),
    ("Curaçao",         "Curaçao",         "Curacao",               1520,  10,   30,  5, 25, 20,  0.0),
    # Grupp F
    ("Nederländerna",   "Netherlands",     "Netherlands",           1959,  10,  850, 82, 80, 78,  0.0),
    ("Japan",           "Japan",           "Japan",                 1879,  15,  320, 45, 60, 85,  0.0),
    ("Sverige",         "Sweden",          "Sweden",                1800,  30,  360, 58, 66, 70,  0.0),
    ("Tunisien",        "Tunisia",         "Tunisia",               1680,   5,   90, 35, 40, 45,  0.0),
    # Grupp G
    ("Belgien",         "Belgium",         "Belgium",               1849, -20,  600, 60, 70, 70,  0.0),
    ("Egypten",         "Egypt",           "Egypt",                 1700,  10,  180, 40, 45, 45,  0.0),
    ("Iran",            "Iran",            "Iran",                  1750,  10,   90, 40, 40, 55,  0.0),
    ("Nya Zeeland",     "New Zealand",     "New Zealand",           1500,  10,   40, 20, 35, 55,  0.0),
    # Grupp H
    ("Spanien",         "Spain",           "Spain",                 2171,  10, 1300, 88, 95, 78,  0.0),
    ("Uruguay",         "Uruguay",         "Uruguay",               1890,  15,  480, 80, 60, 45,  0.0),
    ("Saudiarabien",    "Saudi Arabia",    "Saudi Arabia",          1620, -10,   60, 30, 35, 60,  0.0),
    ("Kap Verde",       "Cape Verde",      "Cape Verde",            1560,  10,   60,  8, 30, 20,  0.0),
    # Grupp I
    ("Frankrike",       "France",          "France",                2063,  10, 1250, 92, 88, 82,  0.0),
    ("Senegal",         "Senegal",         "Senegal",               1869,  50,  450, 50, 52, 40,  0.0),
    ("Norge",           "Norway",          "Norway",                1922,  60,  520, 40, 60, 60,  0.0),
    ("Irak",            "Iraq",            "Iraq",                  1640,  10,   40, 30, 35, 45,  0.0),
    # Grupp J
    ("Argentina",       "Argentina",       "Argentina",             2113,  15,  700, 95, 78, 60,  0.0),
    ("Algeriet",        "Algeria",         "Algeria",               1740,  10,  200, 45, 50, 45,  0.0),
    ("Österrike",       "Austria",         "Austria",               1820,  20,  360, 45, 62, 60,  0.0),
    ("Jordanien",       "Jordan",          "Jordan",                1620,  15,   30,  5, 35, 45,  0.0),
    # Grupp K
    ("Portugal",        "Portugal",        "Portugal",              1976,  10,  950, 60, 80, 55,  0.0),
    ("DR Kongo",        "DR Congo",        "DR Congo",              1650,  10,  180, 30, 45, 35,  0.0),
    ("Uzbekistan",      "Uzbekistan",      "Uzbekistan",            1640,  10,   70,  5, 35, 45,  0.0),
    ("Colombia",        "Colombia",        "Colombia",              1998,  20,  520, 60, 62, 55,  0.0),
    # Grupp L
    ("England",         "England",         "England",               2042,  10, 1300, 80,100, 82,  0.0),
    ("Kroatien",        "Croatia",         "Croatia",               1933,  25,  380, 78, 70, 45,  0.0),
    ("Ghana",           "Ghana",           "Ghana",                 1660,  10,  160, 35, 50, 40,  0.0),
    ("Panama",          "Panama",          "Panama",                1640,  10,   60, 25, 40, 45,  0.0),
]

# Alias: andra stavningar som eloratings.net eller en CSV kan använda.
ELO_ALIASES = {
    "united states": "United States", "usa": "United States",
    "turkiye": "Turkey", "türkiye": "Turkey", "turkey": "Turkey",
    "czech republic": "Czechia", "czechia": "Czechia",
    "bosnia": "Bosnia and Herzegovina",
    "bosnia and herzegovina": "Bosnia and Herzegovina",
    "bosnia-herzegovina": "Bosnia and Herzegovina",
    "cote d'ivoire": "Ivory Coast", "côte d'ivoire": "Ivory Coast",
    "ivory coast": "Ivory Coast",
    "curacao": "Curacao", "curaçao": "Curacao",
    "cape verde": "Cape Verde", "cabo verde": "Cape Verde",
    "dr congo": "DR Congo", "congo dr": "DR Congo",
    "democratic republic of the congo": "DR Congo",
    "south korea": "South Korea", "korea republic": "South Korea",
    "republic of korea": "South Korea",
}


# ----------------------------------------------------------------------------
# NORMALISERING
# ----------------------------------------------------------------------------
def _minmax(values):
    """Skala en lista till 0–100. Allt lika -> 50."""
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [50.0 for _ in values]
    return [100.0 * (v - lo) / (hi - lo) for v in values]


def ranking_scores(elo_now):
    """① Ranking: min–max över lagens aktuella Elo."""
    keys = list(elo_now)
    scaled = _minmax([elo_now[k] for k in keys])
    return {k: round(s, 1) for k, s in zip(keys, scaled)}


def form_scores(elo_now, elo_prev):
    """③ Form: Elo-delta, symmetriskt runt 50 (oförändrad=50)."""
    keys = list(elo_now)
    deltas = {k: elo_now[k] - elo_prev.get(k, elo_now[k]) for k in keys}
    maxabs = max((abs(d) for d in deltas.values()), default=0.0)
    if maxabs < 1e-9:
        return {k: 50.0 for k in keys}
    out = {}
    for k in keys:
        s = 50.0 + 50.0 * deltas[k] / maxabs
        out[k] = round(max(0.0, min(100.0, s)), 1)
    return out


def talent_scores(cies):
    """② Talang: log(truppvärde) -> min–max (dämpar de extrema topptrupperna)."""
    keys = list(cies)
    logs = [math.log(max(1.0, float(cies[k]))) for k in keys]
    scaled = _minmax(logs)
    return {k: round(s, 1) for k, s in zip(keys, scaled)}


def compute_mss(elo_now, elo_prev, cfg):
    """Slår ihop allt till MSS per lag."""
    R = ranking_scores(elo_now)
    F = form_scores(elo_now, elo_prev)
    T = talent_scores({k: cfg[k]["cies"] for k in cfg})

    rows = {}
    for k in cfg:
        sub = {
            "R": R.get(k, 50.0),
            "T": T.get(k, 50.0),
            "F": F.get(k, 50.0),
            "M": float(cfg[k]["M"]),
            "K": float(cfg[k]["K"]),
            "S": float(cfg[k]["S"]),
        }
        base = sum(WEIGHTS[f] * sub[f] for f in WEIGHTS)
        ctx = float(cfg[k].get("ctx", 0.0))
        mss = max(0.0, min(100.0, base + ctx))
        rows[k] = {
            "sv": cfg[k]["sv"], "en": cfg[k]["en"],
            "elo_now": round(elo_now.get(k, 0.0), 1),
            "elo_prev": round(elo_prev.get(k, elo_now.get(k, 0.0)), 1),
            "R": sub["R"], "T": sub["T"], "F": sub["F"],
            "M": sub["M"], "K": sub["K"], "S": sub["S"],
            "mss_base": round(base, 1),
            "context": round(ctx, 1),
            "mss": round(mss, 1),
        }
    return rows


# ----------------------------------------------------------------------------
# ELO-HÄMTNING (live)
# ----------------------------------------------------------------------------
def _norm_name(s):
    return s.strip().strip('"').lower()


def _elo_lookup_table():
    """Bygg {normaliserat namn -> kanoniskt elo-namn} för alla 48 lag + alias."""
    tbl = {}
    for t in TEAMS:
        tbl[_norm_name(t[2])] = t[2]
    for a, canon in ELO_ALIASES.items():
        tbl[_norm_name(a)] = canon
    return tbl


def fetch_elo(url):
    """
    Hämta {kanoniskt elo-namn -> rating} från en eloratings.net TSV-fil.
    Heuristisk: i varje rad letas ett känt lagnamn + en numerisk rating i
    fönstret [ELO_MIN, ELO_MAX]. Returnerar endast våra 48 lag.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (mss_update)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8", "replace")

    name_tbl = _elo_lookup_table()
    wanted = {t[2] for t in TEAMS}
    out = {}
    reader = csv.reader(io.StringIO(raw), delimiter="\t")
    for row in reader:
        if not row:
            continue
        canon = None
        rating = None
        for cell in row:
            c = cell.strip()
            key = _norm_name(c)
            if canon is None and key in name_tbl:
                canon = name_tbl[key]
            if rating is None:
                try:
                    v = float(c)
                except ValueError:
                    continue
                if ELO_MIN <= v <= ELO_MAX:
                    rating = v
        if canon in wanted and rating is not None and canon not in out:
            out[canon] = rating
    return out


# ----------------------------------------------------------------------------
# KONFIG (CIES + omdömesfaktorer)
# ----------------------------------------------------------------------------
def config_from_seeds():
    """Bygg konfig-dict från de inbäddade självtest-frönna (nyckel = elo-namn)."""
    cfg = {}
    for (sv, en, elo, elo_now, d12, cies, M, K, S, ctx) in TEAMS:
        cfg[elo] = {"sv": sv, "en": en, "cies": cies, "M": M, "K": K, "S": S, "ctx": ctx}
    return cfg


def write_example_input(path):
    """Skriv mss_input.example.json som mall att fylla med riktiga CIES-värden m.m."""
    payload = {
        "_comment": ("Fyll i riktiga värden. cies = truppvärde i miljoner EUR (CIES "
                     "Football Observatory). M/K/S = omdömespoäng 0-100 (Meriter, "
                     "Kultur, Socioekonomi). ctx = kontextnudge i MSS-poang "
                     "(hemmaplan/hojd/skador), far vara negativ. Elo (Ranking+Form) "
                     "hamtas live fran eloratings.net och behover INTE anges har. "
                     "Vill du ange Elo manuellt: lagg till elo_now / elo_prev per lag."),
        "teams": {},
    }
    for (sv, en, elo, elo_now, d12, cies, M, K, S, ctx) in TEAMS:
        payload["teams"][elo] = {"sv": sv, "en": en, "cies": cies,
                                 "M": M, "K": K, "S": S, "ctx": ctx}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("Skrev mall:", path)


def load_config(path):
    """Läs mss_input.json (cies + M/K/S + ev. ctx) per lag.

    Elo-fält i konfigen är RESERV vid skarp körning — live-data från eloratings.net
    vinner när den går att hämta:
      elo_now  : reserv-Elo om live-hämtningen failar (så automatiken aldrig stannar).
      d12      : uppskattad 12-mån-förändring; används för Form (elo_prev = elo_now − d12)
                 när fjolårs-Elo inte kunde hämtas live.
      elo_prev : valfri explicit reserv för 12-mån-Elo (annars härleds den ur d12)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    teams = data.get("teams", data)
    seeds = {t[2]: t for t in TEAMS}
    cfg, override_now, override_prev, d12 = {}, {}, {}, {}
    for elo, vals in teams.items():
        if elo not in seeds:
            print("  ! okänt lagnamn i konfig, hoppar över:", elo, file=sys.stderr)
            continue
        sv = vals.get("sv", seeds[elo][0])
        en = vals.get("en", seeds[elo][1])
        cfg[elo] = {
            "sv": sv, "en": en,
            "cies": float(vals["cies"]),
            "M": float(vals["M"]), "K": float(vals["K"]), "S": float(vals["S"]),
            "ctx": float(vals.get("ctx", 0.0)),
        }
        if "elo_now" in vals:
            override_now[elo] = float(vals["elo_now"])
        if "elo_prev" in vals:
            override_prev[elo] = float(vals["elo_prev"])
        if "d12" in vals:
            d12[elo] = float(vals["d12"])
    return cfg, override_now, override_prev, d12


# ----------------------------------------------------------------------------
# UTSKRIFT
# ----------------------------------------------------------------------------
def print_table(rows):
    order = sorted(rows, key=lambda k: rows[k]["mss"], reverse=True)
    print("\n  #  LAG                 MSS   R    T    F    M    K    S   (Elo)")
    print("  " + "-" * 66)
    for i, k in enumerate(order, 1):
        r = rows[k]
        print(f"  {i:>2} {r['sv'][:18]:<18} {r['mss']:>5} "
              f"{r['R']:>4.0f} {r['T']:>4.0f} {r['F']:>4.0f} "
              f"{r['M']:>4.0f} {r['K']:>4.0f} {r['S']:>4.0f}  {r['elo_now']:>6.0f}")


def write_output(rows, path, source="live"):
    import datetime
    payload = {
        "model": "Oscars funderingar (Klementmodellen)",
        "source": source,                     # "live" | "selftest" | "placeholder"
        "generated": datetime.date.today().isoformat(),
        "weights": WEIGHTS,
        "n_teams": len(rows),
        "teams": rows,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("\nSkrev", path, f"({len(rows)} lag, source={source}).")


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Räknar MSS för VM 2026 (Elo + CIES).")
    ap.add_argument("--selftest", action="store_true",
                    help="Kör hela kedjan med inbäddad exempeldata, utan nät.")
    ap.add_argument("--init", action="store_true",
                    help="Skriv mss_input.example.json att fylla i, och avsluta.")
    ap.add_argument("--input", default="mss_input.json",
                    help="Konfig med CIES-värden + omdömesfaktorer (skarp körning).")
    ap.add_argument("--output", default="mss.json", help="Utfil.")
    ap.add_argument("--year", type=int, default=None,
                    help="Årsfil för 12-mån-Elo (default: i fjol).")
    args = ap.parse_args()

    if args.init:
        write_example_input("mss_input.example.json")
        return

    if args.selftest:
        print("SJÄLVTEST — inbäddad exempeldata, ingen nätverkstrafik.")
        elo_now = {t[2]: float(t[3]) for t in TEAMS}
        elo_prev = {t[2]: float(t[3] - t[4]) for t in TEAMS}  # elo_prev = elo_now - d12
        cfg = config_from_seeds()
        rows = compute_mss(elo_now, elo_prev, cfg)
        print_table(rows)
        write_output(rows, "mss.selftest.json", source="selftest")
        # sanity-asserts
        assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "vikter summerar inte till 1"
        assert len(rows) == 48, "förväntade 48 lag"
        for r in rows.values():
            assert 0.0 <= r["mss"] <= 100.0, "MSS utanför 0–100"
        print("Självtest OK — 48 lag, vikter=1.0, alla MSS i [0,100].")
        return

    # ---- skarp körning ----
    import datetime
    year = args.year or (datetime.date.today().year - 1)
    print("SKARP KÖRNING.")
    print("Läser konfig:", args.input)
    cfg, ov_now, ov_prev, d12_map = load_config(args.input)

    print("Hämtar aktuell Elo:", ELO_NOW_URL)
    try:
        fetched_now = fetch_elo(ELO_NOW_URL)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print("  ! Kunde inte hämta aktuell Elo:", e, file=sys.stderr)
        fetched_now = {}
    # Live-data VINNER; konfigens elo_now är RESERV så automatiken aldrig failar helt.
    elo_now = dict(ov_now); elo_now.update(fetched_now)
    print(f"  Elo nu: {len(elo_now)} lag — {len(fetched_now)} live, "
          f"{len([k for k in ov_now if k not in fetched_now])} ur konfig-reserv.")

    prev_url = ELO_PREV_URL_TEMPLATE.format(year=year)
    print(f"Hämtar Elo för 12 mån sedan ({year}):", prev_url)
    try:
        fetched_prev = fetch_elo(prev_url)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print("  ! Kunde inte hämta fjolårs-Elo:", e, file=sys.stderr)
        fetched_prev = {}
    # Live fjolårs-Elo vinner; saknas den härleds elo_prev = elo_now − d12 (konfig).
    elo_prev = dict(ov_prev); elo_prev.update(fetched_prev)
    derived = 0
    for k in elo_now:
        if k not in elo_prev:
            elo_prev[k] = elo_now[k] - d12_map.get(k, 0.0); derived += 1
    print(f"  Elo 12 mån: {len(fetched_prev)} live, {derived} härledda ur d12.")

    missing = [cfg[k]["sv"] for k in cfg if k not in elo_now]
    if missing:
        print("  ! Saknar aktuell Elo för:", ", ".join(missing), file=sys.stderr)
        print("    (Lägg till elo_now/elo_prev för dem i konfigen, eller verifiera",
              "ELO_NOW_URL/parsern.)", file=sys.stderr)
    if not elo_now:
        print("AVBRYTER: ingen Elo-data. Verifiera eloratings.net-endpointen "
              "(ELO_NOW_URL) eller ange elo_now per lag i konfigen.", file=sys.stderr)
        sys.exit(1)

    # lag utan aktuell Elo: använd fjolårsvärdet om det finns, annars hoppa
    for k in list(cfg):
        if k not in elo_now:
            if k in elo_prev:
                elo_now[k] = elo_prev[k]
            else:
                del cfg[k]
    for k in cfg:
        elo_prev.setdefault(k, elo_now[k])

    rows = compute_mss(elo_now, elo_prev, cfg)
    print_table(rows)
    write_output(rows, args.output)


if __name__ == "__main__":
    main()
