"""Petite IA gratuite (Ollama, modèle local) : analyse chaque avis de data/avis.json qui n'a pas
encore d'analyse. S'arrête après IA_MINUTES minutes pour respecter la durée d'un balayage.
"""
import json
import os
import time
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
FICHIER = RACINE / "data" / "avis.json"
OLLAMA = "http://127.0.0.1:11434/api/chat"
MODELE = os.environ.get("MODELE", "gemma4:e2b")
IA_MINUTES = float(os.environ.get("IA_MINUTES", "150"))

SCHEMA = {
    "type": "object",
    "properties": {
        "pertinence": {"type": "integer", "minimum": 0, "maximum": 100},
        "type": {"type": "string", "enum": ["Aménagement intérieur / réno", "Bâtiment neuf / agrandissement", "Hors sujet"]},
        "resume": {"type": "string"},
        "pointsAttention": {"type": "array", "items": {"type": "string"}},
        "recommandation": {"type": "string", "enum": ["Go", "À vérifier", "No-go"]},
        "raison": {"type": "string"},
    },
    "required": ["pertinence", "type", "resume", "pointsAttention", "recommandation", "raison"],
}


def consigne(cfg):
    return f"""Tu aides un entrepreneur général québécois à repérer les appels d'offres SEAO qui valent la peine.
Sa cible : {cfg['portee']}.
Ce qui l'intéresse : travaux de bâtiment réalisés par un entrepreneur général — aménagement ou réaménagement intérieur,
rénovation, réfection (y compris enveloppe, façade, fenêtres, maçonnerie d'un bâtiment), construction d'un bâtiment neuf
ou agrandissement. Mots-clés utiles : {', '.join(cfg['mots_cles'])}.
Ce qui ne l'intéresse pas : génie civil (rues, aqueducs, ponts, stationnements), travaux d'un seul corps de métier
spécialisé (ascenseurs, chaudières, toiture seule, électricité seule, mécanique seule), entretien, services, fournitures.

Pour l'avis fourni, réponds en JSON :
- pertinence : 0 à 100 (100 = parfaitement dans la cible).
- type : la catégorie qui convient, ou « Hors sujet ».
- resume : 1 ou 2 phrases factuelles en français (portée des travaux, durée si connue).
- pointsAttention : visite obligatoire, délai court, cote de sécurité, milieu occupé, contrat sur demande… (liste vide si rien).
- recommandation : « Go » si pertinent et sans obstacle, « No-go » si hors cible, sinon « À vérifier ».
- raison : une phrase qui explique la recommandation.
N'invente rien : n'utilise que les informations de l'avis."""


def texte_avis(a):
    return "\n".join([
        f"Titre : {a['titre']}",
        f"Organisme : {a.get('organisme') or ''}",
        f"Type d'avis : {a.get('typeAvis') or ''}",
        f"Régions : {', '.join(a.get('regions') or [])}",
        f"Fermeture : {a.get('fermeture') or ''}",
        f"Durée prévue (mois) : {a.get('dureeMois') or 'non précisée'}",
        f"Montant estimé : {a.get('estimation') or 'non publié'}",
        f"Cautionnement de soumission : {a.get('cautionSoumission') or 'non précisé'}",
        f"Contrat sur demande : {'oui' if a.get('surDemande') else 'non'}",
        f"Codes de travaux : {'; '.join(a.get('unspsc') or [])}",
        f"Description : {(a.get('description') or '')[:2500]}",
    ])


def analyser(cfg, a):
    corps = {"model": MODELE, "stream": False, "think": False, "format": SCHEMA,
             "options": {"temperature": 0.1, "num_ctx": 4096},
             "messages": [{"role": "system", "content": consigne(cfg)}, {"role": "user", "content": texte_avis(a)}]}
    req = urllib.request.Request(OLLAMA, data=json.dumps(corps).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        res = json.loads(json.load(r)["message"]["content"])
    res["pertinence"] = max(0, min(100, int(res.get("pertinence", 0))))
    return res


def main():
    cfg = json.loads((RACINE / "config.json").read_text(encoding="utf-8"))
    base = json.loads(FICHIER.read_text(encoding="utf-8"))
    a_faire = [a for a in base["avis"] if "analyse" not in a]
    # Les avis qui ferment le plus tôt d'abord
    a_faire.sort(key=lambda a: a.get("fermeture") or "9999")
    print(f"IA ({MODELE}) : {len(a_faire)} avis à analyser, limite {IA_MINUTES:.0f} min")
    debut, faits = time.time(), 0
    for a in a_faire:
        if (time.time() - debut) / 60 > IA_MINUTES:
            print("  temps écoulé, la suite au prochain balayage")
            break
        t0 = time.time()
        try:
            a["analyse"] = analyser(cfg, a)
        except Exception as e:
            print(f"  échec pour {a['numero']} : {e}")
            continue
        faits += 1
        print(f"  {a['analyse']['pertinence']:>3} {a['analyse']['recommandation']:<10} {time.time() - t0:5.0f}s  {a['titre'][:70]}")
        if faits % 5 == 0:  # sauvegarde régulière : rien n'est perdu si le balayage est coupé
            FICHIER.write_text(json.dumps(base, ensure_ascii=False, indent=0), encoding="utf-8")
    base["meta"]["modele"] = MODELE
    FICHIER.write_text(json.dumps(base, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"Analyses faites : {faits}")


if __name__ == "__main__":
    main()
