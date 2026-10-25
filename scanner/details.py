"""Complète les avis ouverts déjà connus avec la fourchette de prix, les cautionnements et les
informations de dépôt (data/details.json), sans toucher à data/avis.json. Le site fusionne les deux.

Usage : python scanner/details.py   (MAX_DETAILS avis au plus par passage, les manquants d'abord)
"""
import json
import time

from seao import MAX_DETAILS, PAUSE, complement, ecrire, get_json, lire


def main():
    avis = [a for a in lire("avis.json", {"avis": []})["avis"] if a.get("source", "SEAO") == "SEAO" and not a.get("fermeArchive")]
    details = lire("details.json", {})
    ouverts = {a["id"] for a in avis}
    details = {k: v for k, v in details.items() if k in ouverts}  # oublie les avis fermés
    a_faire = [a for a in avis if a["id"] not in details][:MAX_DETAILS]
    print(f"{len(a_faire)} avis à compléter (déjà complétés : {len(details)})")
    for i, a in enumerate(a_faire, 1):
        try:
            details[a["id"]] = complement(get_json(f"avis/{a['id']}/consulter"))
        except Exception as e:
            print(f"  {a.get('numero')} illisible : {e}")
        time.sleep(PAUSE)
        if i % 25 == 0:
            ecrire("details.json", details)
            print(f"  {i}/{len(a_faire)}")
    ecrire("details.json", details)
    print(f"Avis complétés : {len(details)}")


if __name__ == "__main__":
    main()
