# -*- coding: utf-8 -*-
"""API Radar Chantier : données ouvertes OFFICIELLES de SEAO (Données Québec, licence CC-BY 4.0).

Télécharge les fichiers hebdomadaires et mensuels (format OCDS), garde seulement la catégorie
C01 - Bâtiments, fusionne les événements par appel d'offres (avis, addendas, annulations,
soumissions, contrats accordés), puis publie une petite API statique dans api/v1/ :

  api/v1/index.json          description, licence, date de mise à jour, liste des points d'accès
  api/v1/avis-ouverts.json   appels d'offres en cours (C01)
  api/v1/contrats.json       contrats accordés : gagnant, montant, tous les soumissionnaires et leurs prix
  api/v1/entreprises.json    par entreprise : soumissions, contrats gagnés, montants
  api/v1/organismes.json     par donneur d'ouvrage : avis publiés, nombre moyen de soumissionnaires

Utilise seulement la bibliothèque standard de Python.
  python scanner/donnees_ouvertes.py            (mise à jour : nouveaux fichiers seulement)
  python scanner/donnees_ouvertes.py --mois 6   (premier remplissage : 6 derniers fichiers mensuels)
"""
import argparse
import datetime as dt
import json
import os
import statistics
import sys
import tempfile
import urllib.request
from collections import defaultdict

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOSSIER = os.path.join(RACINE, "data", "od")
API = os.path.join(RACINE, "api", "v1")
CKAN = "https://www.donneesquebec.ca/recherche/api/3/action/package_show?id=systeme-electronique-dappel-doffres-seao"
ATTRIBUTION = ("Source : Système électronique d'appel d'offres (SEAO), Secrétariat du Conseil du trésor du Québec, "
               "via Données Québec, licence CC-BY 4.0 (https://www.donneesquebec.ca/licence/#cc-by). "
               "Données traitées par Radar Chantier.")
GARDER_JOURS = 550          # environ 18 mois d'historique
AGENT = "RadarChantier/1.0 (donnees ouvertes SEAO)"


# ------------------------------------------------------------------ outils
def telecharger(url, dest=None):
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=300) as r:
        if dest is None:
            return r.read()
        with open(dest, "wb") as f:
            while True:
                bloc = r.read(1 << 20)
                if not bloc:
                    break
                f.write(bloc)
    return dest


def lire(chemin, defaut):
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return defaut


def ecrire(chemin, donnees, compact=False):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(chemin), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        if compact:
            json.dump(donnees, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(donnees, f, ensure_ascii=False, indent=1)
    os.replace(tmp, chemin)


def est_batiment(tender):
    for it in tender.get("items") or []:
        txt = (it.get("description") or "") + " " + ((it.get("classification") or {}).get("description") or "")
        if txt.strip().upper().startswith("C01") or " C01 " in f" {txt} ":
            return True
    return False


# ------------------------------------------------------------------ fusion des événements OCDS
def fusionner(store, releases):
    """store : {ocid: fiche}. Les événements sont appliqués dans l'ordre chronologique."""
    vus = 0
    for r in sorted(releases, key=lambda x: x.get("date") or ""):
        t = r.get("tender") or {}
        ocid = r.get("ocid")
        if not ocid or (ocid not in store and not est_batiment(t)):
            continue
        f = store.setdefault(ocid, {"ocid": ocid, "addendas": 0, "annule": False, "soumissions": [], "gagnants": []})
        # Les fichiers hebdo et mensuels se recoupent : un même événement n'est appliqué qu'une fois
        rid = r.get("id") or r.get("date")
        deja = f.setdefault("evts", [])
        if rid in deja:
            continue
        deja.append(rid)
        del deja[:-60]
        vus += 1
        tags = r.get("tag") or []
        noms = {p.get("id"): p.get("name") for p in r.get("parties") or []}
        acheteur = next((p for p in r.get("parties") or [] if "buyer" in (p.get("roles") or [])), None)
        if t:
            f["no"] = t.get("id") or f.get("no")
            f["titre"] = t.get("title") or f.get("titre")
            f["statut"] = t.get("status") or f.get("statut")
            f["mode"] = t.get("procurementMethodDetails") or f.get("mode")
            per = t.get("tenderPeriod") or {}
            f["debut"] = per.get("startDate") or f.get("debut")
            f["fin"] = per.get("endDate") or f.get("fin")
            if t.get("numberOfTenderers") is not None:
                f["nbSoumissionnaires"] = t["numberOfTenderers"]
            docs = t.get("documents") or []
            if docs and docs[0].get("url"):
                f["lien"] = docs[0]["url"]
            cats = sorted({(it.get("description") or "")[:60] for it in t.get("items") or [] if it.get("description")})
            if cats:
                f["categories"] = cats
            for tt in t.get("tenderers") or []:
                if tt.get("id") and tt.get("name"):
                    noms.setdefault(tt["id"], tt["name"])
        if acheteur:
            f["organisme"] = acheteur.get("name") or f.get("organisme")
            f["ville"] = (acheteur.get("address") or {}).get("locality") or f.get("ville")
        elif (r.get("buyer") or {}).get("name"):
            f["organisme"] = r["buyer"]["name"]
        if "tenderUpdate" in tags:
            f["addendas"] += 1
        if "tenderCancellation" in tags:
            f["annule"] = True
        # Soumissions : chaque entreprise et son prix (le plus bas d'abord)
        bids = r.get("bids") or []
        if bids:
            sm = {}
            for b in bids:
                nom = noms.get(b.get("id")) or b.get("id")
                if b.get("value") is not None:
                    sm[nom] = float(b["value"])
            if sm:
                f["soumissions"] = sorted(({"entreprise": k, "montant": v} for k, v in sm.items()), key=lambda x: x["montant"])
        # Contrats accordés
        for a in r.get("awards") or []:
            for s in a.get("suppliers") or []:
                g = {"entreprise": s.get("name"), "montant": (a.get("value") or {}).get("amount"), "date": a.get("date") or r.get("date")}
                if g["entreprise"] and g not in f["gagnants"]:
                    f["gagnants"] = [x for x in f["gagnants"] if x["entreprise"] != g["entreprise"]] + [g]
        f["maj"] = r.get("date") or f.get("maj")
    return vus


# ------------------------------------------------------------------ publication de l'API
def publier(store):
    maintenant = dt.datetime.now(dt.timezone.utc)
    limite = (maintenant - dt.timedelta(days=GARDER_JOURS)).isoformat()
    fiches = [f for f in store.values() if (f.get("maj") or "") >= limite]

    def ouvert(f):
        return not f["annule"] and f.get("statut") == "active" and (f.get("fin") or "") >= maintenant.isoformat()

    # « evts » sert seulement à éviter les doublons : on ne le publie pas
    fiches = [{k: v for k, v in f.items() if k != "evts"} for f in fiches]
    ouverts = sorted((f for f in fiches if ouvert(f)), key=lambda f: f.get("fin") or "")
    contrats = sorted((f for f in fiches if f["gagnants"] or f["soumissions"]), key=lambda f: f.get("maj") or "", reverse=True)

    ent = defaultdict(lambda: {"soumissions": 0, "gagnes": 0, "montantGagne": 0.0, "montantsSoumis": []})
    for f in fiches:
        for s in f["soumissions"]:
            e = ent[s["entreprise"]]; e["soumissions"] += 1; e["montantsSoumis"].append(s["montant"])
        for g in f["gagnants"]:
            e = ent[g["entreprise"]]; e["gagnes"] += 1; e["montantGagne"] += float(g["montant"] or 0)
    entreprises = sorted(({"entreprise": k, "soumissions": v["soumissions"], "contratsGagnes": v["gagnes"],
                           "montantGagne": round(v["montantGagne"], 2),
                           "tauxSucces": round(v["gagnes"] / v["soumissions"], 3) if v["soumissions"] else None,
                           "soumissionMediane": round(statistics.median(v["montantsSoumis"]), 2) if v["montantsSoumis"] else None}
                          for k, v in ent.items() if k), key=lambda x: (-x["contratsGagnes"], -x["soumissions"]))

    org = defaultdict(lambda: {"avis": 0, "nb": [], "villes": set()})
    for f in fiches:
        if not f.get("organisme"):
            continue
        o = org[f["organisme"]]; o["avis"] += 1
        n = f.get("nbSoumissionnaires") or (len(f["soumissions"]) or None)
        if n:
            o["nb"].append(n)
        if f.get("ville"):
            o["villes"].add(f["ville"])
    organismes = sorted(({"organisme": k, "avisPublies": v["avis"],
                          "soumissionnairesMoyen": round(sum(v["nb"]) / len(v["nb"]), 1) if v["nb"] else None,
                          "villes": sorted(v["villes"])} for k, v in org.items()), key=lambda x: -x["avisPublies"])

    meta = {"source": ATTRIBUTION, "licence": "CC-BY 4.0", "categorie": "C01 - Bâtiments",
            "miseAJour": maintenant.isoformat(timespec="seconds"),
            "note": "Les données ouvertes de SEAO sont publiées chaque semaine (avec quelques jours de décalage). "
                    "Pour les tout nouveaux avis, Radar Chantier utilise aussi son balayage quotidien.",
            "compteurs": {"avisOuverts": len(ouverts), "contrats": len(contrats), "entreprises": len(entreprises),
                          "organismes": len(organismes), "fichesTotal": len(fiches)},
            "pointsAcces": {"avis-ouverts": "api/v1/avis-ouverts.json", "contrats": "api/v1/contrats.json",
                            "entreprises": "api/v1/entreprises.json", "organismes": "api/v1/organismes.json"}}
    env = lambda donnees: {"source": ATTRIBUTION, "miseAJour": meta["miseAJour"], "nombre": len(donnees), "donnees": donnees}
    ecrire(os.path.join(API, "index.json"), meta)
    ecrire(os.path.join(API, "avis-ouverts.json"), env(ouverts), compact=True)
    ecrire(os.path.join(API, "contrats.json"), env(contrats), compact=True)
    ecrire(os.path.join(API, "entreprises.json"), env(entreprises), compact=True)
    ecrire(os.path.join(API, "organismes.json"), env(organismes), compact=True)
    return meta["compteurs"]


# ------------------------------------------------------------------ programme
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mois", type=int, default=0, help="remplir avec les N derniers fichiers mensuels")
    ap.add_argument("--fichier", help="traiter un fichier JSON local (essai)")
    ap.add_argument("--neuf", action="store_true", help="repartir de zéro (ignore l'historique déjà traité)")
    a = ap.parse_args()

    store = {} if a.neuf else lire(os.path.join(DOSSIER, "fiches.json"), {})
    etat = {"traites": []} if a.neuf else lire(os.path.join(DOSSIER, "etat.json"), {"traites": []})
    if not store and not a.mois and not a.fichier:
        a.mois = 6   # premier passage : 6 mois d'historique

    if a.fichier:
        a_traiter = [{"id": "local:" + os.path.basename(a.fichier), "name": os.path.basename(a.fichier), "chemin": a.fichier}]
    else:
        pkg = json.loads(telecharger(CKAN))["result"]["resources"]
        js = [r for r in pkg if (r.get("format") or "").upper() == "JSON" and r.get("name", "").startswith(("hebdo_", "mensuel_"))]
        mensuels = sorted((r for r in js if r["name"].startswith("mensuel_")), key=lambda r: r["name"])
        hebdos = sorted((r for r in js if r["name"].startswith("hebdo_")), key=lambda r: r["name"])
        choix = (mensuels[-a.mois:] if a.mois else []) + hebdos[-6:]
        a_traiter = [r for r in choix if r["id"] not in etat["traites"]]

    total = 0
    for r in a_traiter:
        print(f"  fichier {r['name']}", flush=True)
        chemin = r.get("chemin")
        tmp = None
        if not chemin:
            fd, tmp = tempfile.mkstemp(suffix=".json"); os.close(fd)
            chemin = telecharger(r["url"], tmp)
        try:
            with open(chemin, encoding="utf-8") as f:
                rel = json.load(f).get("releases") or []
            n = fusionner(store, rel)
            total += n
            print(f"    {len(rel)} événements, {n} en C01 - Bâtiments", flush=True)
            etat["traites"].append(r["id"])
        finally:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)

    # on ne garde que l'historique utile
    limite = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=GARDER_JOURS)).isoformat()
    store = {k: v for k, v in store.items() if (v.get("maj") or "") >= limite}
    etat["traites"] = etat["traites"][-200:]
    etat["dernier"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    ecrire(os.path.join(DOSSIER, "fiches.json"), store, compact=True)
    ecrire(os.path.join(DOSSIER, "etat.json"), etat)
    c = publier(store)
    print(f"API publiée : {c}  (événements traités : {total})")


if __name__ == "__main__":
    sys.exit(main())
