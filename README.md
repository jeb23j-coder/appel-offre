# Appel Offre

Veille des appels d'offres SEAO en bâtiment au Québec (aménagement intérieur / rénovation, bâtiment neuf / agrandissement, max. 15 M$).

- **Site** : `index.html`, publié par GitHub Pages.
- **Balayage** : `scanner/seao.py` lit les avis ouverts de SEAO (catégorie C01 Bâtiments) et met à jour `data/avis.json`.
- **IA gratuite** : `scanner/ia.py` analyse chaque nouvel avis avec un petit modèle Ollama qui roule pendant le balayage.
- **Automatisation** : `.github/workflows/balayage.yml`, chaque jour à 7 h, 11 h et 15 h (heure du Québec).
- **Mots-clés** : `config.json` (modifiable directement sur GitHub).
