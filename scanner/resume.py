"""Courriel quotidien de minuit (heure du Québec), un par profil.

Chaque profil qui a un courriel reçoit UN courriel par jour, avec les critères et le courriel tels
qu'ils sont à minuit (peu importe combien de fois ils ont changé dans la journée) :
  - les nouveaux contrats des dernières 24 h qui correspondent à ses critères ;
  - ses contrats (score 40 et plus) qui ferment dans les 7 prochains jours.
Le courriel est envoyé par Gmail (mot de passe d'application dans les secrets GitHub). data/resume.json empêche un deuxième envoi le même jour.
"""
import datetime as dt
import json
import os
import smtplib
import sys
import urllib.request
from email.message import EmailMessage
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


def envoyer_gmail(dest, sujet, texte):
    """Envoie le courriel par Gmail (SMTP) avec l'adresse et le mot de passe d'application du dépôt."""
    expediteur = os.environ["GMAIL_ADDRESS"]
    msg = EmailMessage()
    msg["From"] = f"Radar Chantier <{expediteur}>"
    msg["To"] = dest
    msg["Subject"] = sujet
    msg.set_content(texte)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as m:
        m.login(expediteur, os.environ["GMAIL_APP_PASSWORD"].replace(" ", ""))
        m.send_message(msg)


def sonner(pid, titre, texte):
    """Notification sur le cellulaire (ntfy), car Gmail ne sonne pas pour un courriel envoyé à soi-même."""
    try:
        v = json.loads(os.environ.get("VARS_JSON") or "{}")
    except ValueError:
        v = {}
    sujet = v.get(f"NTFY_TOPIC_{pid.upper()}") or (v.get("NTFY_TOPIC") if pid == "jonathan" else None)
    if not sujet:
        return
    corps = {"topic": sujet, "title": titre, "message": texte, "click": SITE, "tags": ["email"], "priority": 4}
    req = urllib.request.Request("https://ntfy.sh/", data=json.dumps(corps).encode(), headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=20).close()
    except Exception as e:  # la notification ratée ne bloque pas le courriel
        print(f"  notification cellulaire non envoyée : {e}")


def main():
    maintenant = maintenant_quebec()  # « AAAA-MM-JJTHH:MM » heure du Québec
    jour = maintenant[:10]
    force = "--force" in sys.argv
    # Le robot passe toutes les heures ; le résumé part au premier passage après minuit (heure du Québec),
    # une seule fois par jour, même si GitHub lance le robot en retard.
    etat = json.loads(ETAT.read_text(encoding="utf-8")) if ETAT.exists() else {}
    if etat.get("jour") == jour and not force:
        print(f"Résumé du {jour} déjà envoyé.")
        return
    cfg = json.loads((RACINE / "config.json").read_text(encoding="utf-8"))
    avis = [a for a in json.loads((RACINE / "data" / "avis.json").read_text(encoding="utf-8"))["avis"] if not a.get("fermeArchive")]
    hier = (dt.datetime.fromisoformat(maintenant) - dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    dans7 = (dt.datetime.fromisoformat(maintenant) + dt.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M")

    echecs = 0
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
        sujet = f"Radar Chantier · {len(nouveaux)} nouveau(x) contrat(s) · {jour}"
        try:
            envoyer_gmail(courriel, sujet, texte)
            print(f"{prof['nom']} : résumé envoyé · {len(nouveaux)} nouveaux · {len(bientot)} ferment bientôt")
            sonner(pid, sujet, f"Ton résumé est dans ton courriel. {len(nouveaux)} nouveau(x) · {len(bientot)} ferment dans 7 jours")
        except Exception as e:
            print(f"{prof['nom']} : résumé non envoyé ({type(e).__name__}: {e})")
            echecs += 1
    if echecs:  # on réessaiera au prochain passage, et le robot s'affiche en échec
        sys.exit(1)
    etat["jour"] = jour
    ETAT.write_text(json.dumps(etat), encoding="utf-8")


if __name__ == "__main__":
    main()
