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
MAX_RESULTATS = int(os.environ.get("MAX_RESULTATS", "60"))  # résultats d'ouverture vérifiés par balayage


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
    profils = {k: [p["mots_cles"], p["mots_exclus"], p["montant_max"]] for k, p in cfg["profils"].items()}
    return hashlib.sha1(json.dumps(profils, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:10]


def complement(d):
    """Cautionnement d'exécution, dépôt de la soumission et documents exigés, tirés du détail d'un avis."""
    info = d.get("avisResumeInformation") or {}
    desc = texte((d.get("avisResumeDescription") or {}).get("descriptionHtml"))
    t = sans_accents(desc)
    # Cautionnement / garantie d'exécution : écrit dans la description (pas de case à part dans SEAO)
    m = re.search(r"(garantie|cautionnement)s?\s+d.?execution[^.%]{0,80}?(\d{1,3}(?:[.,]\d+)?)\s*%", t)
    if m:
        execution = f"Oui, {m.group(2).replace('.', ',')} %"
    elif re.search(r"(garantie|cautionnement)s?\s+d.?execution", t):
        execution = "Oui (taux aux documents)"
    else:
        execution = "Non précisé sur l'avis"
    m = re.search(r"(gages|materiaux et services)[^.%]{0,80}?(\d{1,3}(?:[.,]\d+)?)\s*%", t)
    gages = f"Oui, {m.group(2).replace('.', ',')} %" if m else None
    stve = ((info.get("stveOption") or {}).get("descriptionFr") or "")
    if stve.lower().startswith("oui, via seao"):
        mode = "Dépôt électronique sur SEAO"
    elif info.get("stveNomAutreSysteme"):
        mode = f"Dépôt électronique sur {info['stveNomAutreSysteme']}"
    elif stve.lower().startswith("non"):
        mode = "Dépôt papier (en personne ou par la poste)"
    else:
        mode = stve or "Voir les documents d'appel d'offres"
    conditions = []
    for sec in (d.get("avisResumeConditions") or {}).get("conditionSections") or []:
        for c in sec.get("conditions") or []:
            x = texte((c.get("description") or {}).get("descriptionFr"))
            if x and len(x) < 400 and x.lower() not in ("autres conditions", "conditions de conformité"):
                conditions.append(x)
    return {
        "fourchette": (info.get("valeurEstime") or {}).get("descriptionFr"),
        "cautionExecution": execution,
        "cautionGages": gages,
        "depot": {
            "mode": mode,
            "lienAutreSysteme": info.get("stveAdresseAutreSysteme"),
            "limite": (info.get("limiteReceptionOffre") or {}).get("descriptionFr"),
            "adresseDepot": (info.get("adresseRecuperation") or {}).get("descriptionFr"),
            "ouverture": (info.get("dateOuvertureSoumissions") or {}).get("descriptionFr"),
            "adresseOuverture": (info.get("adresseOuverture") or {}).get("descriptionFr"),
        },
        "conditions": conditions[:6],
    }


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
        **complement(d),
    }


def masquer(courriel):
    """« jeb.23.j@gmail.com » -> « j•••@gmail.com » : le site public ne montre jamais l'adresse complète."""
    if "@" not in courriel:
        return ""
    nom, dom = courriel.split("@", 1)
    return f"{nom[:1]}•••@{dom}"


REGIONS_SEAO = ["Bas-Saint-Laurent", "Saguenay–Lac-Saint-Jean", "Capitale-Nationale", "Mauricie", "Estrie", "Montréal",
                "Outaouais", "Abitibi-Témiscamingue", "Côte-Nord", "Nord-du-Québec", "Gaspésie–Îles-de-la-Madeleine",
                "Chaudière-Appalaches", "Laval", "Lanaudière", "Laurentides", "Montérégie", "Centre-du-Québec"]


def fermes_recents(cfg, deja, jours=60, maximum=200):
    """Avis de bâtiment fermés depuis moins de `jours` jours dont le titre contient un mot-clé d'un profil.
    Seules les infos de la liste sont gardées ; les résultats d'ouverture sont ajoutés ensuite."""
    cats = ",".join(str(c) for c in cfg["categories_seao"])
    utc = dt.datetime.now(dt.timezone.utc)
    depuis = (utc - dt.timedelta(days=jours)).strftime("%Y-%m-%dT%H:%M")
    maintenant = utc.strftime("%Y-%m-%dT%H:%M")
    trouves = {}
    for statut in (9, 10, 12):
        try:
            liste = get_json(f"recherche?catIds={cats}&statIds={statut}")["results"]
        except Exception as e:
            print(f"  liste des avis fermés illisible ({statut}) : {e}")
            continue
        for a in liste:
            ferm = (a.get("dateFermetureUtc") or "")[:16]
            if a["uuid"] in deja or not (depuis <= ferm <= maintenant) or a.get("typeAvisId") == 6:
                continue
            if not any(garder(a["titre"], "", p)[0] for p in cfg["profils"].values()):
                continue
            trouves[a["uuid"]] = {
                "id": a["uuid"], "source": "SEAO", "numero": a["numero"].strip(), "titre": a["titre"],
                "organisme": a.get("nomDonneurOuvrage"),
                "regions": [REGIONS_SEAO[i - 1] for i in (a.get("regionIds") or []) if 1 <= i <= 17],
                "fermeture": heure_quebec(a.get("dateFermetureUtc")), "publie": heure_quebec(a.get("datePublicationUtc")),
                "lien": LIEN_AVIS + a["uuid"], "fermeArchive": True, "fermeLe": heure_quebec(a.get("dateFermetureUtc"))[:10],
                "nouveau": False,
            }
    plus_recents = sorted(trouves.values(), key=lambda v: v["fermeture"], reverse=True)[:maximum]
    print(f"Contrats fermés récents ajoutés : {len(plus_recents)}")
    return {v["id"]: v for v in plus_recents}


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
    toutes = {x["id"]: x for x in base["avis"] + autres if x["id"] in ouverts}
    fermes = len(base["avis"]) - sum(1 for x in base["avis"] if x["id"] in ouverts)
    ignores &= ouverts

    # Avis fermés : gardés 90 jours (data/fermes.json) pour aller chercher leurs résultats d'ouverture
    archive = {x["id"]: x for x in lire("fermes.json", [])}
    for x in base["avis"]:
        if x.get("source", "SEAO") == "SEAO" and x["id"] not in ouverts and not x.get("fermeArchive"):
            x.update(fermeArchive=True, fermeLe=maintenant_quebec()[:10], nouveau=False)
            archive[x["id"]] = x
    limite = (dt.date.today() - dt.timedelta(days=90)).isoformat()
    archive = {k: v for k, v in archive.items() if (v.get("fermeLe") or "") >= limite}
    if len(archive) < 30:  # premier remplissage : contrats fermés récemment qui touchent vos métiers
        archive.update(fermes_recents(cfg, archive))

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

    # Résultats d'ouverture (publics) : qui a soumissionné et à quel prix
    n_res = 0
    for x in sorted(archive.values(), key=lambda v: v.get("fermeture") or ""):
        if x.get("resultats") or n_res >= MAX_RESULTATS:
            continue
        try:
            d = get_json(f"avis/get-consulter-resultats-ouverture-publies-for-avis/{x['id']}") or {}
        except Exception as e:
            print(f"  résultats illisibles pour {x.get('numero')} : {e}")
            continue
        finally:
            n_res += 1
            time.sleep(PAUSE)
        soum = d.get("soumissions")
        if soum:
            x["resultats"] = {
                "publie": heure_quebec(d.get("datePublicationResultatsOuverture")),
                "soumissions": sorted(
                    [{"nom": (s.get("soumissionnaire") or {}).get("nomOrganisation") or "?",
                      "montant": (s.get("montantSoumis") or {}).get("value")} for s in soum],
                    key=lambda s: s["montant"] if s["montant"] is not None else 9e15),
            }
    print(f"Avis fermés suivis : {len(archive)} · résultats d'ouverture trouvés : {sum(1 for v in archive.values() if v.get('resultats'))}")

    # Avis Merx ajoutés à la main ou par les alertes courriel (data/merx.json) : gardés tant qu'ils sont ouverts,
    # avec leur analyse IA déjà faite s'il y en a une.
    precedents = {x["id"]: x for x in base["avis"]}
    maintenant = maintenant_quebec()
    for m in lire("merx.json", []):
        if (m.get("fermeture") or "9999") < maintenant:
            continue
        f = precedents.get(m["id"], {})
        f.update(m)
        toutes[m["id"]] = f
    for f in toutes.values():
        f.setdefault("source", "SEAO")

    # Tous les avis sont gardés : l'IA les passe tous en revue. Les critères de chaque profil
    # (Jonathan, Patrick…) servent à trier et à repérer ses contrats potentiels.
    avis, nouveaux_ids = [], []
    for f in toutes.values():
        texte_complet = sans_accents(f"{f['titre']} {f.get('description', '')}")
        f["visiteObligatoire"] = bool(re.search(r"visite[^.]{0,60}obligatoire|obligatoire[^.]{0,30}visite", texte_complet))
        f["profils"] = {}
        for pid, prof in cfg["profils"].items():
            ok, trouves = garder(f["titre"], f.get("description", ""), prof)
            choisis = {m.lower() for m in prof["mots_cles"]}
            f["profils"][pid] = {
                "motsTrouves": trouves,
                "motsOk": ok,
                "familles": [nom for nom, termes in prof.get("familles", {}).items()
                             if any(t.lower() in choisis and re.search(r"\b" + re.escape(sans_accents(t)), texte_complet) for t in termes)],
                "tropCher": bool(f.get("estimation") and f["estimation"] > prof["montant_max"]),
            }
        # Pour l'IA : les mots trouvés par au moins un profil
        f["motsTrouves"] = sorted({m for p in f["profils"].values() for m in p["motsTrouves"]})
        f["motsOk"] = any(p["motsOk"] for p in f["profils"].values())
        for vieux in ("familles", "tropCher", "alertes"):
            f.pop(vieux, None)
        f["nouveau"] = f["id"] not in deja_affiches
        if f["nouveau"]:
            nouveaux_ids.append(f["id"])
        avis.append(f)

    nouveaux = sum(1 for f in avis if f["nouveau"])
    meta = {"date": maintenant_quebec(), "seaoLus": len(liste), "retenus": len(avis), "nouveaux": nouveaux,
            "portee": cfg["portee"], "modele": base["meta"].get("modele"), "empreinte": emp}
    ecrire("avis.json", {"meta": meta, "avis": avis + list(archive.values())})
    ecrire("fermes.json", list(archive.values()))
    ecrire("hors_mots.json", [])
    ecrire("ignores.json", sorted(ignores))
    # Premier balayage avec cette version : pas de notification pour tout l'existant d'un coup
    premiere_fois = not base["meta"].get("empreinte")
    ecrire("a_notifier.json", [] if premiere_fois else nouveaux_ids)
    print(f"Avis : {len(avis)} · nouveaux : {nouveaux} · "
          + " · ".join(f"{pid} : {sum(f['profils'][pid]['motsOk'] for f in avis)} avec ses mots" for pid in cfg["profils"])
          + f" · détails lus : {lus} · fermés retirés : {fermes}")


if __name__ == "__main__":
    main()
