"""Remplace « Mes critères » dans config.json à partir d'une demande créée depuis le site.

Format du texte (rempli automatiquement par le site) :
    Mots-clés: brique, maçonnerie, charpente
    Mots exclus: stationnement, aqueduc
    Régions préférées: Montréal, Laval
    Montant min: 50000
    Montant max: 15000000
Lit /tmp/demande.md (ou $AO_TMP/demande.md) et écrit la réponse dans reponse.md.
"""
import json
import os
import re
import sys
from pathlib import Path

from alertes import REGIONS, champ, liste

TMP = os.environ.get("AO_TMP", "/tmp")
RACINE = Path(__file__).resolve().parent.parent


def montant(valeur):
    chiffres = re.sub(r"[^\d]", "", valeur or "")
    return int(chiffres) if chiffres else None


def main():
    texte = Path(TMP, "demande.md").read_text(encoding="utf-8")
    cfg_path = RACINE / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    mots = liste(champ(texte, "Mots-clés") or champ(texte, "Mots-cles"))
    exclus = liste(champ(texte, "Mots exclus"))
    regions = [r for r in REGIONS if r.lower() in {x.lower() for x in liste(champ(texte, "Régions préférées") or champ(texte, "Regions preferees"))}]
    mmin, mmax = montant(champ(texte, "Montant min")), montant(champ(texte, "Montant max"))
    if not mots:
        Path(TMP, "reponse.md").write_text("Il faut au moins un mot-clé. Recommencez depuis le site.", encoding="utf-8")
        sys.exit(1)
    cfg["mots_cles"] = mots[:200]
    cfg["mots_exclus"] = exclus[:200]
    cfg["regions_preferees"] = regions
    cfg["montant_min"] = mmin or 0
    if mmax:
        cfg["montant_max"] = mmax
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    argent = lambda n: f"{n:,}".replace(",", " ")
    msg = "\n".join([
        "Critères enregistrés.",
        "",
        f"- Mots-clés ({len(mots)}) : {', '.join(mots)}",
        f"- Mots exclus : {', '.join(exclus) or 'aucun'}",
        f"- Régions préférées : {', '.join(regions) or 'aucune'}",
        f"- Montant : {argent(cfg['montant_min'])} $ à {argent(cfg['montant_max'])} $",
        "",
        "Le balayage est relancé : tous les avis seront retriés avec ces critères.",
    ])
    Path(TMP, "reponse.md").write_text(msg, encoding="utf-8")
    print(msg)


if __name__ == "__main__":
    main()
