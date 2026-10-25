"""Ajoute ou supprime une alerte dans config.json à partir d'une demande créée depuis le site.

Usage : python scanner/alertes.py ajouter|supprimer  (le texte de la demande est lu dans /tmp/demande.md)
Format du texte (rempli automatiquement par le site) :
    Nom: Réfection de façade
    Mots: réfection de façade, réfection de parement
    Régions: Montréal, Laval
Écrit le message de réponse dans /tmp/reponse.md.
"""
import json
import re
import sys
import os
from pathlib import Path

TMP = os.environ.get("AO_TMP", "/tmp")  # dossier des fichiers échangés avec le workflow

RACINE = Path(__file__).resolve().parent.parent
REGIONS = ["Bas-Saint-Laurent", "Saguenay–Lac-Saint-Jean", "Capitale-Nationale", "Mauricie", "Estrie", "Montréal",
           "Outaouais", "Abitibi-Témiscamingue", "Côte-Nord", "Nord-du-Québec", "Gaspésie–Îles-de-la-Madeleine",
           "Chaudière-Appalaches", "Laval", "Lanaudière", "Laurentides", "Montérégie", "Centre-du-Québec"]


def champ(texte, nom):
    m = re.search(rf"^\s*{nom}\s*:\s*(.*)$", texte, flags=re.I | re.M)
    return m.group(1).strip() if m else ""


def liste(valeur):
    return [v.strip() for v in re.split(r"[,;\n]", valeur) if v.strip()][:200]


def main():
    action = sys.argv[1]
    texte = Path(TMP, "demande.md").read_text(encoding="utf-8")
    nom = champ(texte, "Nom")[:60]
    cfg_path = RACINE / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    alertes = cfg.setdefault("alertes", [])
    if not nom:
        Path(TMP, "reponse.md").write_text("Je n'ai pas trouvé de nom d'alerte. Recommencez depuis le site.", encoding="utf-8")
        sys.exit(1)

    if action == "supprimer":
        avant = len(alertes)
        cfg["alertes"] = [a for a in alertes if a["nom"].lower() != nom.lower()]
        msg = f"Alerte **{nom}** supprimée." if len(cfg["alertes"]) < avant else f"Aucune alerte nommée **{nom}**."
    else:
        mots = liste(champ(texte, "Mots"))
        regions_demandees = liste(champ(texte, "Régions") or champ(texte, "Regions"))
        regions = [r for r in REGIONS if r.lower() in {x.lower() for x in regions_demandees}]
        if not mots and not regions:
            Path(TMP, "reponse.md").write_text("Une alerte doit avoir au moins un mot ou une région.", encoding="utf-8")
            sys.exit(1)
        nouvelle = {"nom": nom}
        if mots:
            nouvelle["mots"] = mots
        if regions:
            nouvelle["regions"] = regions
        cfg["alertes"] = [a for a in alertes if a["nom"].lower() != nom.lower()] + [nouvelle]
        # Les mots d'une alerte doivent aussi être cherchés par le balayage
        for expr in mots:
            if expr.lower() not in {m.lower() for m in cfg["mots_cles"]}:
                cfg["mots_cles"].append(expr)
        msg = (f"Alerte **{nom}** enregistrée.\n\n- Mots : {', '.join(mots) or '(tous)'}\n"
               f"- Régions : {', '.join(regions) or 'tout le Québec'}\n\n"
               "Vous recevrez une notification dès qu'un nouveau contrat correspond. Le balayage est relancé.")
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(TMP, "reponse.md").write_text(msg, encoding="utf-8")
    print(msg)


if __name__ == "__main__":
    main()
