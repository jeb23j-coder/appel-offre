"""Petite IA gratuite (Ollama, modèle local) : analyse chaque avis de data/avis.json qui n'a pas
encore d'analyse. S'arrête après IA_MINUTES minutes pour respecter la durée d'un balayage.
"""
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
FICHIER = RACINE / "data" / "avis.json"
OLLAMA = "http://127.0.0.1:11434/api/chat"
MODELE = os.environ.get("MODELE", "gemma4:e2b")
IA_MINUTES = float(os.environ.get("IA_MINUTES", "150"))
VERSION = 3  # à augmenter quand les consignes changent : les avis sont alors réanalysés
TYPES = ["Maçonnerie", "Charpenterie / menuiserie", "Maçonnerie + charpenterie", "Bâtiment (nos métiers en partie)", "Hors sujet"]
MODES = ["Soumission directe", "Sous-traitance", "Aucun"]

SCHEMA = {
    "type": "object",
    "properties": {
        "pertinence": {"type": "integer", "minimum": 0, "maximum": 100},
        "type": {"type": "string", "enum": TYPES},
        "resume": {"type": "string"},
        "pointsAttention": {"type": "array", "items": {"type": "string"}},
        "recommandation": {"type": "string", "enum": ["Go", "À vérifier", "No-go"]},
        "mode": {"type": "string", "enum": MODES},
        "raison": {"type": "string"},
    },
    "required": ["pertinence", "type", "resume", "pointsAttention", "recommandation", "mode", "raison"],
}


def consigne(cfg):
    return f"""Tu aides une entreprise québécoise de {cfg['metiers']} à repérer les appels d'offres SEAO qui valent la peine.
Sa cible : {cfg['portee']}.
Ce qui l'intéresse le plus : les contrats où la maçonnerie (brique, pierre, bloc, parement, rejointoiement, linteaux,
cheminées, façades de maçonnerie) ou la charpenterie-menuiserie (charpente et ossature de bois, balcons, galeries,
escaliers, terrasses, cloisons, coffrages, portes et fenêtres, finition intérieure) est le travail principal.
Intéressant aussi : rénovations, réfections, agrandissements et bâtiments neufs où ces métiers ont une part importante.
Mots-clés utiles : {', '.join(sorted({m for p in cfg['profils'].values() for m in p['mots_cles']}))}.
Ce qui ne l'intéresse pas : génie civil (rues, aqueducs, ponts, stationnements), travaux d'autres corps de métier
(électricité, mécanique, plomberie, ventilation, ascenseurs, chaudières), entretien, services, fournitures.

Pour l'avis fourni, réponds en JSON :
- pertinence : 0 à 100 (100 = maçonnerie ou charpenterie est clairement le cœur du contrat ; 50 = projet de bâtiment où ces métiers ont une part ; 0 = aucun lien).
- type : la catégorie qui convient, ou « Hors sujet ».
- resume : 1 ou 2 phrases factuelles en français (portée des travaux, durée si connue).
- pointsAttention : visite obligatoire, délai court, cote de sécurité, milieu occupé, contrat sur demande… (liste vide si rien).
- recommandation : « Go » si pertinent et sans obstacle, « No-go » si hors cible, sinon « À vérifier ».
- mode : « Soumission directe » si l'entreprise peut soumissionner elle-même (contrat surtout de maçonnerie ou de
  charpenterie, de taille modeste) ; « Sous-traitance » si c'est un projet d'entrepreneur général où ses métiers seraient
  un lot à offrir à l'entrepreneur gagnant ; « Aucun » si le contrat ne la concerne pas.
- raison : une phrase qui explique la recommandation.
Un grand projet de rénovation peut contenir un lot de maçonnerie ou de charpenterie sans que le titre le dise : lis la description.
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
        f"Mots-clés de l'entreprise trouvés dans l'avis : {', '.join(a.get('motsTrouves') or []) or 'aucun'}",
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
    res["version"] = VERSION
    return res


def publier(message):
    """Pousse data/ sur GitHub (dans le balayage automatique seulement). Un échec n'arrête pas l'analyse."""
    cmds = [["git", "add", "data"], ["git", "commit", "-q", "-m", message], ["git", "pull", "-q", "--rebase"], ["git", "push", "-q"]]
    for c in cmds:
        if subprocess.run(c, cwd=RACINE).returncode != 0 and c[1] != "commit":
            print(f"  publication partielle impossible ({' '.join(c[:2])}), on continue")
            return


def main():
    cfg = json.loads((RACINE / "config.json").read_text(encoding="utf-8"))
    base = json.loads(FICHIER.read_text(encoding="utf-8"))
    a_faire = [a for a in base["avis"] if (a.get("analyse") or {}).get("version") != VERSION]
    # Les nouveaux avis d'abord, puis ceux avec vos mots-clés, puis ceux qui ferment le plus tôt
    a_faire.sort(key=lambda a: (not a.get("nouveau"), not a.get("motsOk"), a.get("fermeture") or "9999"))
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
        if faits % 25 == 0 and os.environ.get("PUBLIER_EN_COURS"):  # le site se remplit au fur et à mesure
            publier(f"Analyses IA en cours ({faits})")
    base["meta"]["modele"] = MODELE
    FICHIER.write_text(json.dumps(base, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"Analyses faites : {faits}")


if __name__ == "__main__":
    main()
