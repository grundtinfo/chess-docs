# Démarrage rapide

Depuis la racine du projet :

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts/setup_stockfish.py
```

Générer les guides d'ouvertures :

```bash
python scripts/openings.py
```

Générer un rapport pour un joueur Chess.com :

```bash
python scripts/chesscom_report.py NOM_UTILISATEUR --months 1 --max-games 5
```

Les PDF apparaissent à la racine. Les données du rapport sont conservées dans `json/player_NOM_UTILISATEUR/` pour permettre la reprise.

Le rapport contient un sommaire complet, des chapitres 4.X et un sous-chapitre daté pour chaque partie. Chaque partie affiche les couleurs, les ELO estimés et la précision des Blancs et des Noirs. Les parties contre les robots Chess.com sont analysées en priorité lorsque `--max-games` est utilisé.

La précision est calculée à partir des évaluations Stockfish et mise en cache avec la partie. L'ELO estimé combine cette précision avec l'estimation existante, avec une pondération progressive selon le nombre de coups analysés.

## Vérifications

```bash
python -c "import chess, reportlab, stockfish, orjson; print('Dépendances OK')"
python scripts/openings.py --help
python scripts/chesscom_report.py --help
python -m unittest discover -s tests -v
```
