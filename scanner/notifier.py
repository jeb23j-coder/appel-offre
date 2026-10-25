"""Prépare la notification des nouveaux contrats qui correspondent à vos critères (après le balayage
et l'analyse IA) : ceux dont le score de potentiel atteint SEUIL. Le score est le même que sur le site.
Écrit /tmp/notif_titre.txt et /tmp/notif.md (rien si aucun contrat ne passe le seuil).
"""
import json
import os
import urllib.request
from pathlib import Path

TMP = os.environ.get("AO_TMP", "/tmp")  # dossier des fichiers échangés avec le workflow

RACINE = Path(__file__).resolve().parent.parent
SITE = "https://jeb23j-coder.github.io/appel-offre/"
MAX_LIGNES = 40


def argent(n):
    if not n:
        return "montant non publié"
    return f"{n / 1e6:.2f} M$".replace(".", ",") if n >= 1e6 else f"{n:,} $".replace(",", " ")


SEUIL = 60  # « À vérifier » (60-79) et « Priorité » (80-100)


def score(a, meta):
    """Même calcul que sur le site : IA, mots-clés trouvés, région préférée et montant."""
    if a.get("tropCher"):
        return 0
    x = a.get("analyse") or {}
    s = x["pertinence"] * 0.5 if x else (25 if a.get("motsOk") else 0)
    s += min(len(a.get("motsTrouves") or []), 5) * 4
    if set(meta.get("regionsPreferees") or []) & set(a.get("regions") or []):
        s += 10
    est = a.get("estimation")
    if est and (meta.get("montantMin") or 0) <= est <= (meta.get("montantMax") or float("inf")):
        s += 5
    if x.get("recommandation") == "No-go":
        s = min(s, 30)
    return max(0, min(100, round(s)))


def main():
    ids = set(json.loads((RACINE / "data" / "a_notifier.json").read_text(encoding="utf-8")))
    base = json.loads((RACINE / "data" / "avis.json").read_text(encoding="utf-8"))
    meta, avis = base["meta"], base["avis"]
    items = [a for a in avis if a["id"] in ids and score(a, meta) >= SEUIL]
    if not items:
        print("Aucun nouveau contrat au-dessus du seuil à notifier")
        return
    items.sort(key=lambda a: (-score(a, meta), a.get("fermeture") or ""))
    titre = f"{len(items)} nouveau{'x' if len(items) > 1 else ''} contrat{'s' if len(items) > 1 else ''} pour vos critères"
    lignes = [f"Nouveaux appels d'offres SEAO qui correspondent à vos critères. Tout voir : {SITE}", ""]
    for a in items[:MAX_LIGNES]:
        x = a.get("analyse") or {}
        sc = score(a, meta)
        lignes.append(f"### [{a['titre']}]({a.get('lien') or SITE}) — score {sc}{' · Priorité' if sc >= 80 else ''}")
        if x:
            lignes.append(f"- IA : {x.get('mode') or ''} — {x.get('resume', '')}")
        lignes.append(f"- {a.get('organisme') or ''} · {', '.join(a.get('regions') or [])}")
        lignes.append(f"- Fermeture : {(a.get('fermeture') or '').replace('T', ' à ')} · {argent(a.get('estimation'))}")
        if a.get("motsTrouves"):
            lignes.append(f"- Mots-clés trouvés : {', '.join(a['motsTrouves'][:8])}")
        lignes.append("")
    if len(items) > MAX_LIGNES:
        lignes.append(f"… et {len(items) - MAX_LIGNES} autres sur le site : {SITE}")
    Path(TMP, "notif_titre.txt").write_text(titre, encoding="utf-8")
    Path(TMP, "notif.md").write_text("\n".join(lignes), encoding="utf-8")
    print(titre)
    pousser_cellulaire(titre, items)


def pousser_cellulaire(titre, items):
    """Notification sur le cellulaire avec l'application gratuite ntfy (si NTFY_TOPIC est réglé)."""
    sujet = os.environ.get("NTFY_TOPIC")
    if not sujet:
        return
    resume = "\n".join(f"• {a['titre'][:90]}" + (f" ({', '.join(a.get('regions') or [])[:40]})" if a.get("regions") else "")
                       for a in items[:5])
    if len(items) > 5:
        resume += f"\n… et {len(items) - 5} autres"
    corps = {"topic": sujet, "title": f"Appel Offre : {titre}", "message": resume, "click": SITE,
             "tags": ["bell"], "priority": 4}
    req = urllib.request.Request("https://ntfy.sh/", data=json.dumps(corps).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f"Notification cellulaire envoyée ({r.status})")
    except Exception as e:  # la notification par courriel part quand même
        print(f"Notification cellulaire non envoyée : {e}")


if __name__ == "__main__":
    main()
