"""Importe une page de résultats Merx copiée (Ctrl+A, Ctrl+C) dans data/merx.json.

Usage : python scanner/merx_import.py fichier_texte.txt [--tout-le-canada]
Seuls les avis situés au Québec (« QC ») sont gardés, sauf avec --tout-le-canada.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
MOIS = None


def lire_page(texte):
    lignes = [l.strip() for l in texte.splitlines()]
    lignes = [l for l in lignes if l]
    avis = []
    for i, l in enumerate(lignes):
        if l != "CalendarClosing Date":
            continue
        # Bloc : [icône] titre / organisme / [description] / CalendarClosing Date / date / LocationLocation / lieu / Published Date
        debut = i - 1
        while debut > 0 and lignes[debut - 1] not in ("Maple Leaf", "Briefcase") and not lignes[debut - 1].startswith("Published Date"):
            debut -= 1
        bloc = lignes[debut:i]
        if len(bloc) < 2:
            continue
        titre = re.sub(r"\s*\(opens in a new window\)$", "", bloc[0])
        organisme = bloc[1]
        description = " ".join(bloc[2:]) if len(bloc) > 2 else ""
        fermeture = lignes[i + 1] if i + 1 < len(lignes) else ""
        lieu = lignes[i + 3] if i + 3 < len(lignes) and lignes[i + 2] == "LocationLocation" else ""
        publie = next((x.replace("Published Date", "").strip() for x in lignes[i + 2:i + 6] if x.startswith("Published Date")), "")
        avis.append({"titre": titre, "organisme": organisme, "description": description,
                     "fermeture_brute": fermeture, "lieu": lieu, "publie_brut": publie,
                     "prive": i - debut > 0 and debut > 0 and lignes[debut - 1] == "Briefcase"})
    return avis


def date_iso(brute):
    """« 2026/11/10 02:00:00 PM EST » -> « 2026-11-10T14:00 »"""
    m = re.match(r"(\d{4})/(\d{2})/(\d{2})(?:\s+(\d{1,2}):(\d{2})(?::\d{2})?\s*(AM|PM))?", brute or "")
    if not m:
        return None
    y, mo, d, h, mi, ap = m.groups()
    if h is None:
        return f"{y}-{mo}-{d}T00:00"
    h = int(h) % 12 + (12 if ap == "PM" else 0)
    return f"{y}-{mo}-{d}T{h:02d}:{mi}"


REGIONS_QC = {"Outaouais": "Outaouais", "Montréal": "Montréal", "Montreal": "Montréal", "Laval": "Laval", "Montérégie": "Montérégie",
              "Capitale-Nationale": "Capitale-Nationale", "Québec": "Capitale-Nationale", "Estrie": "Estrie", "Mauricie": "Mauricie",
              "Laurentides": "Laurentides", "Lanaudière": "Lanaudière", "Côte-Nord": "Côte-Nord", "Bas-Saint-Laurent": "Bas-Saint-Laurent",
              "Saguenay": "Saguenay–Lac-Saint-Jean", "Abitibi": "Abitibi-Témiscamingue", "Gaspésie": "Gaspésie–Îles-de-la-Madeleine",
              "Chaudière-Appalaches": "Chaudière-Appalaches", "Centre-du-Québec": "Centre-du-Québec", "Nord-du-Québec": "Nord-du-Québec"}


def main():
    texte = Path(sys.argv[1]).read_text(encoding="utf-8")
    tout = "--tout-le-canada" in sys.argv
    trouves = lire_page(texte)
    gardes = [a for a in trouves if tout or re.search(r"\bQC\b|Québec|Quebec", a["lieu"])]
    fichier = RACINE / "data" / "merx.json"
    existants = json.loads(fichier.read_text(encoding="utf-8")) if fichier.exists() else []
    ids = {x["id"] for x in existants}
    ajoutes = 0
    for a in gardes:
        cle = hashlib.sha1(f"{a['titre']}|{a['organisme']}".encode()).hexdigest()[:12]
        if f"merx-{cle}" in ids:
            continue
        region = next((v for k, v in REGIONS_QC.items() if k.lower() in a["lieu"].lower()), a["lieu"].split(",")[0])
        existants.append({
            "id": f"merx-{cle}", "source": "Merx", "numero": cle, "titre": a["titre"], "organisme": a["organisme"],
            "regions": [region], "typeAvis": "Avis Merx", "cautionSoumission": "Voir l'avis sur Merx",
            "estimation": None, "fermeture": date_iso(a["fermeture_brute"]), "publie": date_iso(a["publie_brut"]),
            "description": a["description"], "lien": "https://www.merx.com/",
        })
        ajoutes += 1
    fichier.write_text(json.dumps(existants, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Avis lus sur la page : {len(trouves)} · au Québec : {len(gardes)} · nouveaux ajoutés : {ajoutes}")
    for a in gardes:
        print(f"  {a['titre'][:70]} | {a['organisme']} | {a['lieu']} | ferme {date_iso(a['fermeture_brute'])}")


if __name__ == "__main__":
    main()
