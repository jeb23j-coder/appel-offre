"""Ajoute l'estimation de l'organisme (montant estimé, fourchette) aux contrats fermés de data/fermes.json
qui ne l'ont pas encore, pour comparer le prix gagnant à l'estimation.

Usage : python scanner/estimations_fermes.py   (MAX_DETAILS avis au plus par passage)
"""
import time

from seao import MAX_DETAILS, PAUSE, ecrire, get_json, lire


def main():
    fermes = lire("fermes.json", [])
    a_faire = [f for f in fermes if f.get("resultats") and "estimationVerifiee" not in f][:MAX_DETAILS]
    print(f"{len(a_faire)} contrats fermés à compléter")
    for i, f in enumerate(a_faire, 1):
        try:
            info = get_json(f"avis/{f['id']}/consulter").get("avisResumeInformation") or {}
            f["estimation"] = f.get("estimation") or info.get("montantEstimeContrat")
            f["fourchette"] = f.get("fourchette") or (info.get("valeurEstime") or {}).get("descriptionFr")
            f["estimationVerifiee"] = True
        except Exception as e:
            print(f"  {f.get('numero')} illisible : {e}")
        time.sleep(PAUSE)
        if i % 25 == 0:
            ecrire("fermes.json", fermes)
            print(f"  {i}/{len(a_faire)}")
    ecrire("fermes.json", fermes)
    print(f"Avec estimation : {sum(1 for f in fermes if f.get('estimation'))} sur {len(fermes)}")


if __name__ == "__main__":
    main()
