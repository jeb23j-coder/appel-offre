"""Prépare la notification des nouveaux contrats potentiels (après le balayage et l'analyse IA).

Un contrat est potentiel s'il correspond à une de vos alertes, si l'IA le juge « Go » ou « À vérifier »,
ou, tant qu'il n'est pas encore analysé, s'il contient vos mots-clés. Les contrats au-dessus du montant
maximum et ceux que l'IA juge « No-go » sans alerte sont laissés de côté.
Écrit /tmp/notif_titre.txt et /tmp/notif.md (rien si aucun contrat potentiel).
"""
import json
import os
from pathlib import Path

TMP = os.environ.get("AO_TMP", "/tmp")  # dossier des fichiers échangés avec le workflow

RACINE = Path(__file__).resolve().parent.parent
SITE = "https://jeb23j-coder.github.io/appel-offre/"
MAX_LIGNES = 40


def argent(n):
    if not n:
        return "montant non publié"
    return f"{n / 1e6:.2f} M$".replace(".", ",") if n >= 1e6 else f"{n:,} $".replace(",", " ")


def potentiel(a):
    if a.get("tropCher"):
        return False
    reco = (a.get("analyse") or {}).get("recommandation")
    if a.get("alertes"):
        return True
    if reco:
        return reco in ("Go", "À vérifier")
    return bool(a.get("motsOk"))


def main():
    ids = set(json.loads((RACINE / "data" / "a_notifier.json").read_text(encoding="utf-8")))
    avis = json.loads((RACINE / "data" / "avis.json").read_text(encoding="utf-8"))["avis"]
    items = [a for a in avis if a["id"] in ids and potentiel(a)]
    if not items:
        print("Aucun nouveau contrat potentiel à notifier")
        return
    items.sort(key=lambda a: (not a.get("alertes"), -((a.get("analyse") or {}).get("pertinence") or 0), a.get("fermeture") or ""))
    n_al = sum(1 for a in items if a.get("alertes"))
    titre = f"{len(items)} nouveau{'x' if len(items) > 1 else ''} contrat{'s' if len(items) > 1 else ''} potentiel{'s' if len(items) > 1 else ''}"
    if n_al:
        titre += f" (dont {n_al} pour vos alertes)"
    lignes = [f"Nouveaux appels d'offres SEAO qui correspondent à vos critères. Tout voir : {SITE}", ""]
    for a in items[:MAX_LIGNES]:
        x = a.get("analyse") or {}
        alerte = f" — 🔔 **{', '.join(a['alertes'])}**" if a.get("alertes") else ""
        lignes.append(f"### [{a['titre']}]({a.get('lien') or SITE}){alerte}")
        if x:
            lignes.append(f"- IA : **{x.get('pertinence')} % · {x.get('recommandation')}** — {x.get('resume', '')}")
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


if __name__ == "__main__":
    main()
