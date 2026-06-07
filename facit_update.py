#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
facit_update.py — hämtar faktiska VM 2026-resultat från football-data.org (GRATIS)
och skriver en results.json som VM2026-Facit.html läser in automatiskt.

KÖRS PÅ SERVERSIDAN (din dator, en cron, eller ett GitHub Action) — INTE i webbläsaren,
så att din token aldrig exponeras.

Användning:
    export FOOTBALLDATA_TOKEN="din-gratis-token-från-football-data.org"
    python3 facit_update.py                 # skriver ./results.json
    python3 facit_update.py /sökväg/VM2026/results.json   # valfri målsökväg
    python3 facit_update.py --selftest      # testar mappningen utan nätverk

Behöver bara Python 3 (inga pip-paket). Ladda upp den skapade results.json till
samma mapp som VM2026-Facit.html (/VM2026/). Sidan plockar upp den vid sidladdning.

GRATIS-API: football-data.org  ·  VM = competition-kod WC  ·  v4
  Bas:    https://api.football-data.org
  Anrop:  GET /v4/competitions/WC/matches            (ett anrop hämtar hela turneringen)
  Auth:   HTTP-header  X-Auth-Token: DIN_TOKEN
  Token:  registrera gratis på  https://www.football-data.org/client/register
  Gräns:  10 anrop/minut på gratisnivån (vi gör ett anrop per körning -> inga problem)
  Obs:    gratisnivån har FÖRDRÖJDA resultat (ej sekund-live). För ett facit räcker det
          gott — vi vill bara ha slutresultatet efter matchen.

Om season-filtret skulle ge ett fel (t.ex. om 2026 ännu inte är upplagt): kör med
  export FOOTBALLDATA_SEASON=""   för att hämta innevarande säsong istället.
"""
import os, sys, json, urllib.request, urllib.parse, urllib.error, unicodedata

API_BASE = "https://api.football-data.org"
COMP   = os.environ.get("FOOTBALLDATA_COMP", "WC")        # FIFA World Cup
SEASON = os.environ.get("FOOTBALLDATA_SEASON", "2026")    # VM 2026 (sätt "" för innevarande)

# ---------------------------------------------------------------------------
# Lagdata — MÅSTE spegla VM2026-Facit.html (samma grupper, samma match-id:n)
# (grupp, kortnamn, MSS)
TEAMS = [
 ("A","Mexiko",66),("A","Sydkorea",60),("A","Tjeckien",50),("A","Sydafrika",44),
 ("B","Schweiz",67),("B","Kanada",62),("B","Bosnien",48),("B","Qatar",49),
 ("C","Brasilien",83),("C","Marocko",76),("C","Skottland",52),("C","Haiti",36),
 ("D","Turkiet",58),("D","USA",64),("D","Paraguay",51),("D","Australien",55),
 ("E","Tyskland",80),("E","Ecuador",60),("E","Elfenbenskusten",51),("E","Curacao",33),
 ("F","Nederländerna",78),("F","Japan",69),("F","Sverige",61),("F","Tunisien",49),
 ("G","Belgien",77),("G","Egypten",55),("G","Iran",56),("G","Nya Zeeland",37),
 ("H","Spanien",90),("H","Uruguay",71),("H","Saudiarabien",46),("H","Kap Verde",38),
 ("I","Frankrike",91),("I","Senegal",70),("I","Norge",66),("I","Irak",41),
 ("J","Argentina",89),("J","Österrike",59),("J","Algeriet",51),("J","Jordanien",42),
 ("K","Portugal",82),("K","Colombia",70),("K","DR Kongo",44),("K","Uzbekistan",45),
 ("L","England",84),("L","Kroatien",72),("L","Ghana",43),("L","Panama",50),
]
ROUNDROBIN = [((0, 3), (1, 2)), ((0, 2), (3, 1)), ((0, 1), (2, 3))]

# slutspel: (match-id, hemma-kortnamn, borta-kortnamn)
KO = [
 ("M73","Sydkorea","Kanada"),("M74","Tyskland","Tjeckien"),("M75","Nederländerna","Marocko"),
 ("M76","Brasilien","Japan"),("M77","Frankrike","Sverige"),("M78","Ecuador","Senegal"),
 ("M79","Mexiko","Skottland"),("M80","England","Elfenbenskusten"),("M81","Turkiet","Bosnien"),
 ("M82","Belgien","Algeriet"),("M83","Colombia","Kroatien"),("M84","Spanien","Österrike"),
 ("M85","Schweiz","Norge"),("M86","Argentina","Uruguay"),("M87","Portugal","Iran"),
 ("M88","USA","Egypten"),
 ("M89","Frankrike","Tyskland"),("M90","Marocko","Kanada"),("M91","Brasilien","Senegal"),
 ("M92","England","Mexiko"),("M93","Spanien","Colombia"),("M94","Belgien","Turkiet"),
 ("M95","Argentina","USA"),("M96","Portugal","Norge"),
 ("M97","Frankrike","Marocko"),("M98","Spanien","Belgien"),("M99","Brasilien","England"),
 ("M100","Argentina","Portugal"),("M101","Frankrike","Spanien"),("M102","Argentina","Brasilien"),
 ("M103","Spanien","Brasilien"),("M104","Frankrike","Argentina"),
]

# vårt kortnamn -> engelskt namn (som football-data.org returnerar)
SHORT2EN = {
 "Mexiko":"Mexico","Sydafrika":"South Africa","Sydkorea":"South Korea","Tjeckien":"Czechia",
 "Schweiz":"Switzerland","Kanada":"Canada","Bosnien":"Bosnia and Herzegovina","Qatar":"Qatar",
 "Brasilien":"Brazil","Marocko":"Morocco","Skottland":"Scotland","Haiti":"Haiti",
 "Turkiet":"Turkey","USA":"USA","Paraguay":"Paraguay","Australien":"Australia",
 "Tyskland":"Germany","Ecuador":"Ecuador","Elfenbenskusten":"Ivory Coast","Curacao":"Curacao",
 "Nederländerna":"Netherlands","Japan":"Japan","Sverige":"Sweden","Tunisien":"Tunisia",
 "Belgien":"Belgium","Egypten":"Egypt","Iran":"Iran","Nya Zeeland":"New Zealand",
 "Spanien":"Spain","Uruguay":"Uruguay","Saudiarabien":"Saudi Arabia","Kap Verde":"Cape Verde",
 "Frankrike":"France","Senegal":"Senegal","Norge":"Norway","Irak":"Iraq",
 "Argentina":"Argentina","Österrike":"Austria","Algeriet":"Algeria","Jordanien":"Jordan",
 "Portugal":"Portugal","Colombia":"Colombia","DR Kongo":"DR Congo","Uzbekistan":"Uzbekistan",
 "England":"England","Kroatien":"Croatia","Ghana":"Ghana","Panama":"Panama",
}

# extra engelska/lokala varianter API:et kan tänkas använda -> vårt kortnamn
EXTRA_ALIASES = {
 "czech republic":"Tjeckien","turkiye":"Turkiet","türkiye":"Turkiet",
 "united states":"USA","united states of america":"USA","usmnt":"USA",
 "cote d ivoire":"Elfenbenskusten","côte d'ivoire":"Elfenbenskusten","cote divoire":"Elfenbenskusten",
 "ivory coast":"Elfenbenskusten","curaçao":"Curacao","cabo verde":"Kap Verde",
 "cape verde islands":"Kap Verde","bosnia":"Bosnien","bosnia herzegovina":"Bosnien",
 "bosnia and herzegovina":"Bosnien","bosnia-herzegovina":"Bosnien",
 "korea republic":"Sydkorea","republic of korea":"Sydkorea","korea south":"Sydkorea",
 "south korea":"Sydkorea","dr congo":"DR Kongo","democratic republic of the congo":"DR Kongo",
 "congo dr":"DR Kongo","congo democratic republic":"DR Kongo","saudi arabia":"Saudiarabien",
 "ir iran":"Iran","iran islamic republic":"Iran","czechia":"Tjeckien","new zealand":"Nya Zeeland",
}

# football-data.org status för färdigspelad match
DONE = {"FINISHED", "AWARDED"}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.lower().replace(".", " ").replace("-", " ").split())


def build_alias_map():
    m = {}
    for short, en in SHORT2EN.items():
        m[norm(en)] = short
        m[norm(short)] = short
    for k, short in EXTRA_ALIASES.items():
        m[norm(k)] = short
    return m

ALIAS = build_alias_map()


def short_of(name):
    return ALIAS.get(norm(name))


def build_index():
    """frozenset({homeShort, awayShort}) -> (id, homeShort, awayShort)"""
    idx = {}
    groups = {}
    for t in TEAMS:
        groups.setdefault(t[0], []).append(t)
    for L in sorted(groups):
        g = sorted(groups[L], key=lambda t: -t[2])
        for omg, pairs in enumerate(ROUNDROBIN, start=1):
            for (a, b) in pairs:
                hs, as_ = g[a][1], g[b][1]
                mid = "G%s%d%d%d" % (L, omg, a, b)
                idx[frozenset((hs, as_))] = (mid, hs, as_)
    for (mid, hs, as_) in KO:
        idx[frozenset((hs, as_))] = (mid, hs, as_)
    return idx

INDEX = build_index()


def final_score(m):
    """slutresultat (home, away) ur en football-data.org-match, eller None.
    Vi använder score.fullTime (resultatet efter ev. förlängning). OBS: matcher
    som avgörs på straffar kan ha oavgjort i fullTime + score.winner = vinnaren;
    sådana kan du finjustera för hand i facit-sidans ifyllningsläge vid behov."""
    ft = (m.get("score") or {}).get("fullTime") or {}
    h, a = ft.get("home"), ft.get("away")
    if isinstance(h, int) and isinstance(a, int):
        return h, a
    return None


def is_finished(m):
    return m.get("status") in DONE


def map_results(matches, results, log):
    """fyller results-dict {id:[h,a]} från en lista football-data.org-matcher"""
    for m in matches:
        if not isinstance(m, dict) or not is_finished(m):
            continue
        ht = m.get("homeTeam") or {}
        at = m.get("awayTeam") or {}
        hn, an = ht.get("name"), at.get("name")
        if not hn or not an:            # slutspelsmatch där lagen ännu inte är klara
            continue
        sc = final_score(m)
        if not sc:
            continue
        hs, as_ = short_of(hn), short_of(an)
        if not hs or not as_:
            log.append("Okänt lagnamn: %s vs %s" % (hn, an)); continue
        hit = INDEX.get(frozenset((hs, as_)))
        if not hit:
            log.append("Match ej i prognosen (slutspel kan ha divergerat): %s vs %s" % (hs, as_))
            continue
        mid, our_home, _our_away = hit
        gh, ga = sc
        results[mid] = [gh, ga] if hs == our_home else [ga, gh]  # orientera till vårt hemma/borta
    return results


def fetch_json(path, params):
    url = API_BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={
        "X-Auth-Token": TOKEN,
        "Accept": "application/json",
        "User-Agent": "vm2026-facit/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "ignore")
        except Exception:
            pass
        msg = ""
        try:
            j = json.loads(body) if body else {}
            msg = j.get("message") or j.get("error") or ""
        except Exception:
            msg = body[:200]
        if e.code == 429:
            raise RuntimeError("Hastighetsgräns nådd (10 anrop/min på gratisnivån). Vänta en minut. %s" % msg)
        if e.code in (401, 403):
            raise RuntimeError("Nekad (HTTP %s) — kontrollera din token i X-Auth-Token. %s" % (e.code, msg))
        if e.code == 400:
            raise RuntimeError("Felaktig förfrågan (HTTP 400). Prova FOOTBALLDATA_SEASON=\"\" för innevarande säsong. %s" % msg)
        raise RuntimeError("HTTP %s: %s" % (e.code, msg or e.reason))
    if isinstance(data, dict) and data.get("message") and "matches" not in data:
        raise RuntimeError("API-fel: %s" % data.get("message"))
    return data


def run(results, log):
    params = {}
    if SEASON:
        params["season"] = SEASON
    data = fetch_json("/v4/competitions/%s/matches" % COMP, params)
    matches = data.get("matches") or []
    map_results(matches, results, log)
    rs = data.get("resultSet") or {}
    print("  /v4/competitions/%s/matches%s: %d matcher i svaret (API anger spelade: %s)" % (
        COMP, (" season=%s" % SEASON if SEASON else ""), len(matches), rs.get("played", "?")))


def selftest():
    """testar mappningen utan nätverk med påhittade slutresultat (football-data.org-format)"""
    mock = [
        {"status": "FINISHED", "homeTeam": {"name": "Mexico"}, "awayTeam": {"name": "South Africa"},
         "score": {"winner": "HOME_TEAM", "duration": "REGULAR", "fullTime": {"home": 2, "away": 1}}},
        {"status": "FINISHED", "homeTeam": {"name": "Sweden"}, "awayTeam": {"name": "Japan"},
         "score": {"winner": "DRAW", "duration": "REGULAR", "fullTime": {"home": 1, "away": 1}}},
        {"status": "FINISHED", "homeTeam": {"name": "France"}, "awayTeam": {"name": "Argentina"},
         "score": {"winner": "HOME_TEAM", "duration": "EXTRA_TIME", "fullTime": {"home": 2, "away": 1}}},  # M104
        {"status": "FINISHED", "homeTeam": {"name": "Türkiye"}, "awayTeam": {"name": "Bosnia and Herzegovina"},
         "score": {"winner": "AWAY_TEAM", "duration": "REGULAR", "fullTime": {"home": 0, "away": 3}}},  # -> M81, omvänd
        {"status": "IN_PLAY", "homeTeam": {"name": "Spain"}, "awayTeam": {"name": "Uruguay"},
         "score": {"winner": None, "duration": "REGULAR", "fullTime": {"home": 1, "away": 0}}},  # pågår -> ej
        {"status": "TIMED", "homeTeam": {"name": None}, "awayTeam": {"name": None},
         "score": {"winner": None, "duration": "REGULAR", "fullTime": {"home": None, "away": None}}},  # ej spelad
    ]
    res, log = {}, []
    map_results(mock, res, log)
    print("SELFTEST resultat:", json.dumps(res, ensure_ascii=False))
    print("SELFTEST logg:", log)
    assert res.get("M104") == [2, 1], "finalen ska mappas till M104 2-1"
    assert res.get("M81") == [0, 3], "Türkiye 0-3 Bosnien ska bli M81 [0,3]"
    assert res.get("GA103") == [2, 1], "Mexiko-Sydafrika ska bli GA103 [2,1]"
    assert any(v == [1, 1] for k, v in res.items() if k.startswith("GF")), "grupp F 1-1 ska finnas"
    assert not any(v == [1, 0] for v in res.values()), "pågående match ska inte räknas"
    assert len(res) == 4, "exakt fyra färdiga matcher ska mappas (inte pågående/ej spelade)"
    print("SELFTEST: OK ✓  (%d matcher mappade)" % len(res))


def main():
    global TOKEN
    args = list(sys.argv[1:])
    if "--selftest" in args:
        selftest(); return
    TOKEN = (os.environ.get("FOOTBALLDATA_TOKEN") or os.environ.get("FOOTBALL_DATA_TOKEN") or "").strip()
    if not TOKEN:
        print("Fel: sätt miljövariabeln FOOTBALLDATA_TOKEN med din gratis-token från")
        print("     https://www.football-data.org/client/register")
        sys.exit(1)
    out = next((a for a in args if not a.startswith("-")), "results.json")
    results, log = {}, []
    print("Hämtar VM 2026-resultat från football-data.org ...")
    try:
        run(results, log)
    except Exception as e:
        print("Hämtning misslyckades:", e); sys.exit(2)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=0)
    print("Skrev %s med %d färdigspelade matcher." % (out, len(results)))
    if log:
        print("Noteringar (%d):" % len(log))
        for line in log[:20]:
            print("  -", line)
    print("Ladda upp %s till /VM2026/ bredvid VM2026-Facit.html." % out)


if __name__ == "__main__":
    main()
