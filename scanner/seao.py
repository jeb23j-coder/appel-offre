"""Balayage SEAO : lit les avis ouverts (catégorie C01 Bâtiments), trie par mots-clés,
récupère le détail des nouveaux avis retenus et met à jour data/avis.json.

Les avis fermés disparaissent du fichier. Les avis écartés (hors sujet ou trop chers) sont
retenus dans data/ignores.json pour ne pas relire leur détail à chaque balayage.
"""
import datetime as dt
import hashlib
import html
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DONNEES = RACINE / "data"
API = "https://api.seao.gouv.qc.ca/prod/api/"
LIEN_AVIS = "https://seao.gouv.qc.ca/avis-resultat-recherche/consulter?ItemId="
PAUSE = 1.5          # secondes entre deux appels de détail, pour rester poli avec SEAO
MAX_DETAILS = int(os.environ.get("MAX_DETAILS", "150"))


def get_json(chemin, essais=4):
    req = urllib.request.Request(API + chemin, headers={"User-Agent": "Mozilla/5.0 (appel-offre)", "Origin": "https://seao.gouv.qc.ca"})
    for i in range(essais):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)["apiData"]
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == essais - 1:
                raise
            attente = int(e.headers.get("Retry-After") or 0) or 15 * (i + 1)
            print(f"  SEAO demande de ralentir, pause de {attente} s")
            time.sleep(attente)
        except urllib.error.URLError:
            if i == essais - 1:
                raise
            time.sleep(10 * (i + 1))  # coupure réseau passagère


def sans_accents(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def texte(html_brut):
    if not html_brut:
        return ""
    t = re.sub(r"<(br|/p|/li|/div)[^>]*>", "\n", html_brut, flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    return re.sub(r"[ \t\xa0]+", " ", re.sub(r"\n\s*\n+", "\n", t)).strip()


def heure_quebec(utc_iso):
    """UTC -> heure de l'Est (HNE/HAE) au format AAAA-MM-JJTHH:MM, sans dépendre de tzdata."""
    if not utc_iso:
        return None
    d = dt.datetime.fromisoformat(utc_iso.replace("Z", "+00:00")).replace(tzinfo=None)
    y = d.year
    debut = dt.datetime(y, 3, 8 + (6 - dt.date(y, 3, 8).weekday()) % 7, 7)   # 2e dimanche de mars, 2 h HNE
    fin = dt.datetime(y, 11, 1 + (6 - dt.date(y, 11, 1).weekday()) % 7, 6)   # 1er dimanche de nov., 2 h HAE
    return (d - dt.timedelta(hours=4 if debut <= d < fin else 5)).strftime("%Y-%m-%dT%H:%M")


def maintenant_quebec():
    return heure_quebec(dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


def fermeture_officielle(info):
    """Heure légale affichée sur l'avis (« 2026-11-16 Au plus tard 11:00 »), sinon conversion de l'UTC."""
    txt = (info.get("limiteReceptionOffre") or {}).get("descriptionFr") or ""
    m = re.match(r"(\d{4}-\d{2}-\d{2})\D+(\d{1,2}):(\d{2})", txt)
    if m:
        return f"{m.group(1)}T{int(m.group(2)):02d}:{m.group(3)}"
    return heure_quebec(info.get("dateLimiteReceptionOffresUtc"))


def chercher_mots(texte_avis, cfg):
    """Mots-clés et mots exclus présents dans le texte (sans tenir compte des accents ni des majuscules)."""
    t = sans_accents(texte_avis)
    trouves = [m for m in cfg["mots_cles"] if re.search(r"\b" + re.escape(sans_accents(m)), t)]
    exclus = [m for m in cfg["mots_exclus"] if re.search(r"\b" + re.escape(sans_accents(m)), t)]
    return trouves, exclus


def garder(titre, description, cfg):
    """Règle de recherche : l'avis est gardé s'il contient au moins un mot-clé, dans le titre ou la
    description, sauf si le titre ne contient que des mots exclus."""
    trouves, _ = chercher_mots(f"{titre}\n{description}", cfg)
    t_trouves, t_exclus = chercher_mots(titre, cfg)
    if t_exclus and not t_trouves:
        return False, trouves
    return bool(trouves), trouves


def empreinte(cfg):
    return hashlib.sha1(json.dumps([cfg["mots_cles"], cfg["mots_exclus"], cfg["montant_max"], cfg.get("alertes")], ensure_ascii=False).encode()).hexdigest()[:10]


def fiche(a):
    d = get_json(f"avis/{a['uuid']}/consulter")
    info = d.get("avisResumeInformation") or {}
    gar = d.get("avisResumeGarantieSoumission") or {}
    natures = [n.get("descriptionFr") for n in (gar.get("naturesGaranties") or []) if isinstance(n, dict)]
    caution = ", ".join(x for x in [", ".join(filter(None, natures)), texte(gar.get("valeurGarantieHtml"))] if x)
    cat = d.get("avisResumeCategorieUnspsc") or {}
    return {
        "id": a["uuid"],
        "numero": a["numero"].strip(),
        "titre": info.get("titre") or a["titre"],
        "organisme": (d.get("avisResumeInformationDO") or {}).get("nomOrganisation") or a.get("nomDonneurOuvrage"),
        "regions": [r.get("descriptionFr") for r in (info.get("regionsLivraison") or [])],
        "typeAvis": (info.get("typeAvis") or {}).get("descriptionFr"),
        "cautionSoumission": caution or "Non précisé sur l'avis",
        "estimation": info.get("montantEstimeContrat"),
        "dureeMois": info.get("dureePrevueSansOptions"),
        "surDemande": bool(info.get("contratSurDemande")),
        "fermeture": fermeture_officielle(info),
        "publie": heure_quebec(info.get("datePublicationUtc")),
        "categorie": (cat.get("categorie") or {}).get("descriptionFr"),
        "unspsc": [u.get("descriptionFr") for u in (cat.get("unspsc") or [])][:6],
        "description": texte((d.get("avisResumeDescription") or {}).get("descriptionHtml"))[:3000],
        "lien": LIEN_AVIS + a["uuid"],
    }


def lire(nom, defaut):
    p = DONNEES / nom
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else defaut


def ecrire(nom, contenu):
    DONNEES.mkdir(exist_ok=True)
    (DONNEES / nom).write_text(json.dumps(contenu, ensure_ascii=False, indent=0), encoding="utf-8")


MOTS_VIDES = {"de", "du", "des", "la", "le", "les", "d", "l", "et", "a", "au", "aux", "en", "pour", "sur"}


def correspond_alerte(f, alerte):
    """Une alerte correspond si l'avis est dans une de ses régions (si elle en a) et contient une de
    ses expressions. Une expression correspond quand tous ses mots importants sont dans le texte,
    peu importe l'ordre et le pluriel (« réfection de façade » trouve « réfection des façades »)."""
    if alerte.get("regions") and not set(alerte["regions"]) & set(f.get("regions") or []):
        return False
    if alerte.get("montant_max") and f.get("estimation") and f["estimation"] > alerte["montant_max"]:
        return False
    if not alerte.get("mots"):
        return True  # alerte seulement par région
    t = sans_accents(f"{f.get('titre', '')} {f.get('description', '')}")
    for expr in alerte["mots"]:
        mots = [m for m in re.findall(r"[a-z0-9]+", sans_accents(expr)) if m not in MOTS_VIDES]
        if mots and all(re.search(r"\b" + re.escape(m), t) for m in mots):
            return True
    return False


def main():
    cfg = json.loads((RACINE / "config.json").read_text(encoding="utf-8"))
    base = lire("avis.json", {"meta": {}, "avis": []})
    autres = lire("hors_mots.json", [])          # fiches déjà lues mais sans mot-clé
    ignores = set(lire("ignores.json", []))
    emp = empreinte(cfg)
    if base["meta"].get("empreinte") != emp:
        ignores = set()                           # mots-clés changés : tout est réévalué
    cats = ",".join(str(c) for c in cfg["categories_seao"])
    liste = get_json(f"recherche?catIds={cats}&statIds=6")["results"]
    print(f"SEAO : {len(liste)} avis ouverts lus")

    ouverts = {a["uuid"] for a in liste}
    deja_affiches = {x["id"] for x in base["avis"]}
    deja_alertes = {x["id"]: set(x.get("alertes") or []) for x in base["avis"]}
    toutes = {x["id"]: x for x in base["avis"] + autres if x["id"] in ouverts}
    fermes = len(base["avis"]) - sum(1 for x in base["avis"] if x["id"] in ouverts)
    ignores &= ouverts

    lus = 0
    for a in liste:
        u = a["uuid"]
        if u in toutes or u in ignores:
            continue
        if a.get("typeAvisId") == 6:  # programmes d'homologation : pas des contrats
            ignores.add(u)
            continue
        if lus >= MAX_DETAILS:
            continue  # sera lu au prochain balayage
        try:
            f = fiche(a)
        except Exception as e:  # un avis illisible ne bloque pas le balayage
            print(f"  détail illisible pour {a['numero']} : {e}")
            continue
        finally:
            lus += 1
            time.sleep(PAUSE)
        f["vuLe"] = maintenant_quebec()
        toutes[u] = f

    # Tous les avis sont gardés : l'IA les passe tous en revue. Les mots-clés et les alertes
    # servent à trier et à repérer les contrats potentiels.
    avis, nouveaux_ids = [], []
    for f in toutes.values():
        ok, trouves = garder(f["titre"], f.get("description", ""), cfg)
        f["motsTrouves"] = trouves
        f["motsOk"] = ok
        f["tropCher"] = bool(f.get("estimation") and f["estimation"] > cfg["montant_max"])
        f["nouveau"] = f["id"] not in deja_affiches
        # Une alerte par région seulement exige aussi un mot-clé, pour ne pas signaler un stationnement
        f["alertes"] = [al["nom"] for al in cfg.get("alertes", []) if correspond_alerte(f, al) and (al.get("mots") or ok)]
        nouvelles_alertes = [n for n in f["alertes"] if n not in deja_alertes.get(f["id"], set())]
        if f["nouveau"] or nouvelles_alertes:
            nouveaux_ids.append(f["id"])
        avis.append(f)

    nouveaux = sum(1 for f in avis if f["nouveau"])
    meta = {"date": maintenant_quebec(), "seaoLus": len(liste), "retenus": len(avis), "nouveaux": nouveaux,
            "portee": cfg["portee"], "modele": base["meta"].get("modele"), "empreinte": emp,
            "alertes": cfg.get("alertes", []), "motsCles": cfg["mots_cles"], "motsExclus": cfg["mots_exclus"],
            "regionsPreferees": cfg.get("regions_preferees", []), "montantMin": cfg.get("montant_min", 0), "montantMax": cfg["montant_max"]}
    ecrire("avis.json", {"meta": meta, "avis": avis})
    ecrire("hors_mots.json", [])
    ecrire("ignores.json", sorted(ignores))
    # Premier balayage avec cette version : pas de notification pour tout l'existant d'un coup
    premiere_fois = not base["meta"].get("empreinte")
    ecrire("a_notifier.json", [] if premiere_fois else nouveaux_ids)
    print(f"Avis : {len(avis)} · nouveaux : {nouveaux} · avec vos mots-clés : {sum(f['motsOk'] for f in avis)} "
          f"· à vérifier pour notification : {0 if premiere_fois else len(nouveaux_ids)} · détails lus : {lus} · fermés retirés : {fermes}")


if __name__ == "__main__":
    main()
