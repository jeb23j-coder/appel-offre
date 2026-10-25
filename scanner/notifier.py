"""Notifications des nouveaux contrats, profil par profil (Jonathan, Patrick…).

Pour chaque profil, un nouveau contrat est signalé si son score de potentiel (même calcul que le
site) atteint SEUIL avec les critères de ce profil. Chaque profil reçoit :
  - un courriel, à l'adresse choisie sur le site (chiffrée, déchiffrée ici avec la clé privée) ;
  - une notification sur son cellulaire (application ntfy, canal privé du profil).
Pour le propriétaire du dépôt, le message est aussi écrit dans /tmp/notif_titre.txt et /tmp/notif.md
(le workflow en fait une demande GitHub, qui lui envoie aussi un courriel).
"""
import json
import os
import urllib.request
from pathlib import Path

from courriel import dechiffrer

TMP = os.environ.get("AO_TMP", "/tmp")  # dossier des fichiers échangés avec le workflow
RACINE = Path(__file__).resolve().parent.parent
SITE = "https://jeb23j-coder.github.io/appel-offre/"
MAX_LIGNES = 40
SEUIL = 60  # « À vérifier » (60-79) et « Priorité » (80-100)


def argent(n):
    if not n:
        return "montant non publié"
    return f"{n / 1e6:.2f} M$".replace(".", ",") if n >= 1e6 else f"{n:,} $".replace(",", " ")


def score(a, pid, prof):
    """Même calcul que sur le site : IA, mots-clés trouvés, région préférée et montant, pour un profil."""
    p = (a.get("profils") or {}).get(pid, {})
    if p.get("tropCher"):
        return 0
    x = a.get("analyse") or {}
    s = x["pertinence"] * 0.5 if x else (25 if p.get("motsOk") else 0)
    s += min(len(p.get("motsTrouves") or []), 5) * 4
    if set(prof.get("regions_preferees") or []) & set(a.get("regions") or []):
        s += 10
    est = a.get("estimation")
    if est and (prof.get("montant_min") or 0) <= est <= (prof.get("montant_max") or float("inf")):
        s += 5
    if x.get("recommandation") == "No-go":
        s = min(s, 30)
    return max(0, min(100, round(s)))


def message(items, pid, prof):
    titre = f"{len(items)} nouveau{'x' if len(items) > 1 else ''} contrat{'s' if len(items) > 1 else ''} pour {prof['nom']}"
    lignes = [f"Nouveaux appels d'offres SEAO qui correspondent aux critères de {prof['nom']}. Tout voir : {SITE}", ""]
    for a in items[:MAX_LIGNES]:
        x = a.get("analyse") or {}
        sc = score(a, pid, prof)
        lignes.append(f"### [{a['titre']}]({a.get('lien') or SITE}) — score {sc}{' · Priorité' if sc >= 80 else ''}")
        if x:
            lignes.append(f"- IA : {x.get('mode') or ''} — {x.get('resume', '')}")
        lignes.append(f"- {a.get('organisme') or ''} · {', '.join(a.get('regions') or [])}")
        lignes.append(f"- Fermeture : {(a.get('fermeture') or '').replace('T', ' à ')} · {argent(a.get('estimation'))}")
        mots = ((a.get("profils") or {}).get(pid) or {}).get("motsTrouves") or []
        if mots:
            lignes.append(f"- Mots-clés trouvés : {', '.join(mots[:8])}")
        lignes.append("")
    if len(items) > MAX_LIGNES:
        lignes.append(f"… et {len(items) - MAX_LIGNES} autres sur le site : {SITE}")
    return titre, "\n".join(lignes)


def variables():
    """Réglages privés du dépôt (canaux ntfy), passés par le workflow en JSON."""
    try:
        return json.loads(os.environ.get("VARS_JSON") or "{}")
    except ValueError:
        return {}


def envoyer(sujet, courriel, titre, items):
    """Notification cellulaire (ntfy) et courriel (relayé par ntfy) pour un profil."""
    if not sujet:
        return
    resume = "\n".join(f"• {a['titre'][:90]}" + (f" ({', '.join(a.get('regions') or [])[:40]})" if a.get("regions") else "")
                       for a in items[:5])
    if len(items) > 5:
        resume += f"\n… et {len(items) - 5} autres"
    corps = {"topic": sujet, "title": f"Radar Chantier : {titre}", "message": resume, "click": SITE, "tags": ["bell"], "priority": 4}
    if courriel:
        corps["email"] = courriel
    req = urllib.request.Request("https://ntfy.sh/", data=json.dumps(corps).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f"  notification envoyée ({r.status}){' + courriel' if courriel else ''}")
    except Exception as e:  # une notification ratée ne bloque pas les autres
        print(f"  notification non envoyée : {e}")


def main():
    ids = set(json.loads((RACINE / "data" / "a_notifier.json").read_text(encoding="utf-8")))
    cfg = json.loads((RACINE / "config.json").read_text(encoding="utf-8"))
    avis = json.loads((RACINE / "data" / "avis.json").read_text(encoding="utf-8"))["avis"]
    vars_ = variables()
    for pid, prof in cfg["profils"].items():
        items = [a for a in avis if a["id"] in ids and score(a, pid, prof) >= SEUIL]
        if not items:
            print(f"{prof['nom']} : aucun nouveau contrat au-dessus du seuil")
            continue
        items.sort(key=lambda a: (-score(a, pid, prof), a.get("fermeture") or ""))
        titre, texte = message(items, pid, prof)
        print(f"{prof['nom']} : {titre}")
        try:
            courriel = dechiffrer(prof.get("courrielChiffre"))
        except Exception as e:
            print(f"  courriel illisible pour {prof['nom']} : {e}")
            courriel = None
        sujet = vars_.get(f"NTFY_TOPIC_{pid.upper()}") or (vars_.get("NTFY_TOPIC") if pid == "jonathan" else None)
        envoyer(sujet, courriel, titre, items)
        if pid == "jonathan":  # demande GitHub pour le propriétaire du dépôt
            Path(TMP, "notif_titre.txt").write_text(titre, encoding="utf-8")
            Path(TMP, "notif.md").write_text(texte, encoding="utf-8")


if __name__ == "__main__":
    main()
