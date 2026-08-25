# Chess-Docs

Outil Python qui produit des guides PDF d'échecs et des rapports d'analyse à partir de données JSON et des archives publiques de Chess.com.

## État actuel

- Génération des guides d'ouvertures depuis `json/opening_*.json`.
- Analyse des positions et des meilleurs coups avec Stockfish quand le moteur est disponible.
- Identification des ouvertures via `Openix`, avec traduction locale des noms.
- Génération de rapports joueurs Chess.com, avec cache par partie et reprise des analyses incomplètes.
- Rendu des échiquiers, flèches, FEN et notation française via ReportLab et `python-chess`.
- Le parcours des pièges est présent dans `scripts/traps.py`, mais il est actuellement bloqué par l'import de `OllamaManager`, absent de `classes/engines.py`.

## Installation

Python 3.12 est recommandé. Depuis la racine du dépôt :

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`requirements.txt` contient notamment `python-chess`, `reportlab`, `stockfish`, `requests`, `orjson`, `openix` et `aider-chat`.

## Utilisation

Installer Stockfish (optionnel) :

```bash
python scripts/setup_stockfish.py
```

Le script télécharge Stockfish 18 dans `~/stockfish`, teste le binaire et tente de créer `/usr/local/sbin/stockfish`. Le moteur cherche d'abord un binaire local dans `stockfish/stockfish/`, puis `stockfish` dans le `PATH`.

Générer toutes les ouvertures :

```bash
python scripts/openings.py
```

Exemples d'options :

```bash
python scripts/openings.py --opening fried_liever_attack --stockfish-depth 18 --verbose
python scripts/openings.py --opening sicilian_defense --stockfish-depth 20
```

Les PDF sont écrits à la racine, avec le nom `guide_opening_<source>.pdf`.

Générer un rapport Chess.com :

```bash
python scripts/chesscom_report.py <joueur>
python scripts/chesscom_report.py <joueur> --months 3 --max-games 10 --verbose
python scripts/chesscom_report.py <joueur> --opponent <adversaire> --incomplete-only
python scripts/chesscom_report.py <joueur> --game-id 123456789
```

Le rapport est enregistré sous `<joueur>_report_avance.pdf` (ou `<joueur>_vs_<adversaire>_report_avance.pdf`). Les parties sont conservées dans `json/player_<joueur>/game_<id>.json`. Les parties terminées disposant d'un PGN sont téléchargées depuis l'API publique Chess.com; `--max-games 0` signifie toutes les parties candidates.

## Données et cache

- `json/trappes_data.json` : données des pièges.
- `json/opening_*.json` : sources des guides d'ouvertures.
- `json/player_<joueur>/` : état détaillé des parties analysées.
- `json/cache_analyses.json` : cache des commentaires et traductions d'ouvertures.
- `logs/` : journaux éventuels.

Les caches et les rapports PDF sont ignorés par Git. Les analyses de parties peuvent contenir des données récupérées depuis Chess.com : vérifier les conditions d'utilisation du service avant une redistribution.

## Tests et diagnostic

```bash
python -m unittest discover -s tests -v
python -m compileall -q classes scripts tests
python scripts/openings.py --help
python scripts/chesscom_report.py --help
```

## Organisation

`classes/` contient les utilitaires, le cache, Stockfish, l'analyse et le rendu PDF. `scripts/` contient les points d'entrée. `json/` contient les sources et caches. `tests/` contient les tests du rapport joueur. Les documents techniques et procédures se trouvent dans `docs/`.
