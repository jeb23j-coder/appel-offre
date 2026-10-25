"""Balayage SEAO : lit les avis ouverts (catégorie C01 Bâtiments), trie par mots-clés,
récupère le détail des nouveaux avis retenus et met à jour data/avis.json.

Les avis fermés disparaissent du fichier. Les avis écartés (hors sujet ou trop chers) sont
retenus dans data/ignores.json pour ne pas relire leur détail à chaque balayage.
"""
import datetime as dt
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


def tri_mots_cles(titre, cfg):
    t = sans_accents(titre)
    trouves = [m for m in cfg["mots_cles"] if sans_accents(m) in t]
    exclus = [m for m in cfg["mots_exclus"] if sans_accents(m) in t]
    if trouves and not exclus:
        return "candidat", trouves, exclus
    if exclus and not trouves:
        return "rejete", trouves, exclus
    return "a_classer", trouves, exclus  # l'IA tranchera


def fiche(a, statut, trouves):
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
        "tri": statut,
        "motsTrouves": trouves,
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


def main():
    cfg = json.loads((RACINE / "config.json").read_text(encoding="utf-8"))
    base = lire("avis.json", {"meta": {}, "avis": []})
    ignores = set(lire("ignores.json", []))
    cats = ",".join(str(c) for c in cfg["categories_seao"])
    liste = get_json(f"recherche?catIds={cats}&statIds=6")["results"]
    print(f"SEAO : {len(liste)} avis ouverts lus")

    ouverts = {a["uuid"] for a in liste}
    avis = [x for x in base["avis"] if x["id"] in ouverts]           # retire les avis fermés
    fermes = len(base["avis"]) - len(avis)
    for x in avis:
        x["nouveau"] = False
    connus = {x["id"] for x in avis} | ignores
    ignores &= ouverts                                                # oublie les écartés fermés

    nouveaux, lus = 0, 0
    for a in liste:
        if a["uuid"] in connus:
            continue
        statut, trouves, _ = tri_mots_cles(a["titre"], cfg)
        if statut == "rejete" or a.get("typeAvisId") == 6:
            ignores.add(a["uuid"])
            continue
        if lus >= MAX_DETAILS:
            continue  # sera lu au prochain balayage
        try:
            f = fiche(a, statut, trouves)
        except Exception as e:  # un avis illisible ne bloque pas le balayage
            print(f"  détail illisible pour {a['numero']} : {e}")
            continue
        finally:
            lus += 1
            time.sleep(PAUSE)
        if f["estimation"] and f["estimation"] > cfg["montant_max"]:
            ignores.add(a["uuid"])
            continue
        f["nouveau"] = True
        f["vuLe"] = maintenant_quebec()
        avis.append(f)
        nouveaux += 1

    meta = {"date": maintenant_quebec(), "seaoLus": len(liste), "retenus": len(avis), "nouveaux": nouveaux,
            "portee": cfg["portee"], "modele": base["meta"].get("modele")}
    ecrire("avis.json", {"meta": meta, "avis": avis})
    ecrire("ignores.json", sorted(ignores))
    print(f"Nouveaux : {nouveaux} · détails lus : {lus} · fermés retirés : {fermes} · retenus : {len(avis)}")


if __name__ == "__main__":
    main()
