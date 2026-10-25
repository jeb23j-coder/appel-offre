"""Courriel quotidien de minuit (heure du Québec), un par profil.

Chaque profil qui a un courriel reçoit UN courriel par jour, avec les critères et le courriel tels
qu'ils sont à minuit (peu importe combien de fois ils ont changé dans la journée) :
  - les nouveaux contrats des dernières 24 h qui correspondent à ses critères ;
  - ses contrats (score 40 et plus) qui ferment dans les 7 prochains jours.
Le courriel est envoyé par ntfy (sans mot de passe). data/resume.json empêche un deuxième envoi le même jour.
"""
import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path

from courriel import dechiffrer
from notifier import score
from seao import maintenant_quebec

RACINE = Path(__file__).resolve().parent.parent
SITE = "https://jeb23j-coder.github.io/appel-offre/"
ETAT = RACINE / "data" / "resume.json"
SEUIL = 40


def argent(n):
    if not n:
        return "montant non publié"
    return f"{n / 1e6:.2f} M$".replace(".", ",") if n >= 1e6 else f"{n:,} $".replace(",", " ")


def ligne(a, sc):
    return f"• [{sc}] {a['titre'][:100]} — {a.get('organisme') or ''}, {', '.join(a.get('regions') or [])[:40]} · ferme le {(a.get('fermeture') or '').replace('T', ' à ')} · {argent(a.get('estimation'))}"


def main():
    maintenant = maintenant_quebec()  # « AAAA-MM-JJTHH:MM » heure du Québec
    jour, heure = maintenant[:10], int(maintenant[11:13])
    force = "--force" in sys.argv
    if heure != 0 and not force:
        print(f"Il est {maintenant[11:]} au Québec : le résumé part seulement à minuit.")
        return
    etat = json.loads(ETAT.read_text(encoding="utf-8")) if ETAT.exists() else {}
    if etat.get("jour") == jour and not force:
        print(f"Résumé du {jour} déjà envoyé.")
        return
    cfg = json.loads((RACINE / "config.json").read_text(encoding="utf-8"))
    avis = [a for a in json.loads((RACINE / "data" / "avis.json").read_text(encoding="utf-8"))["avis"] if not a.get("fermeArchive")]
    hier = (dt.datetime.fromisoformat(maintenant) - dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    dans7 = (dt.datetime.fromisoformat(maintenant) + dt.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M")

    for pid, prof in cfg["profils"].items():
        try:
            courriel = dechiffrer(prof.get("courrielChiffre"))
        except Exception as e:
            print(f"{prof['nom']} : courriel illisible ({type(e).__name__})")
            courriel = None
        if not courriel:
            print(f"{prof['nom']} : pas de courriel, pas de résumé.")
            continue
        notes = [(a, score(a, pid, prof)) for a in avis]
        miens = [(a, s) for a, s in notes if s >= SEUIL and (a.get("fermeture") or "") >= maintenant]
        nouveaux = sorted([(a, s) for a, s in miens if (a.get("vuLe") or a.get("publie") or "") >= hier], key=lambda x: -x[1])
        bientot = sorted([(a, s) for a, s in miens if (a.get("fermeture") or "") <= dans7], key=lambda x: x[0].get("fermeture") or "")
        lignes = [f"Bonjour {prof['nom']},", "",
                  f"Vos critères donnent {len(miens)} contrats ouverts. Tout voir : {SITE}", ""]
        lignes.append(f"NOUVEAUX DEPUIS HIER ({len(nouveaux)})")
        lignes += [ligne(a, s) for a, s in nouveaux[:12]] or ["Aucun nouveau contrat pour vos critères."]
        lignes += ["", f"FERMENT DANS LES 7 PROCHAINS JOURS ({len(bientot)})"]
        lignes += [ligne(a, s) for a, s in bientot[:10]] or ["Aucun."]
        texte = "\n".join(lignes)
        if len(texte) > 3800:  # limite d'un message
            texte = texte[:3800] + f"\n… la suite sur le site : {SITE}"
        corps = {"topic": f"radar-resume-{pid}", "title": f"Radar Chantier · {len(nouveaux)} nouveau(x) contrat(s) · {jour}",
                 "message": texte, "click": SITE, "email": courriel, "tags": ["construction"]}
        req = urllib.request.Request("https://ntfy.sh/", data=json.dumps(corps).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                print(f"{prof['nom']} : résumé envoyé ({r.status}) · {len(nouveaux)} nouveaux · {len(bientot)} ferment bientôt")
        except Exception as e:
            print(f"{prof['nom']} : résumé non envoyé ({e})")
    etat["jour"] = jour
    ETAT.write_text(json.dumps(etat), encoding="utf-8")


if __name__ == "__main__":
    main()
