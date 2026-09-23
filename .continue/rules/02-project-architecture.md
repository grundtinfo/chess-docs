# 02-project-architecture.md

## Project Structure

Le projet est organisé en plusieurs dossiers principaux :
* `classes/`: Contient les classes Python qui gèrent l'analyse des échecs, la génération de rapports PDF et l'intégration avec Stockfish.
* `json/`: Contient les données JSON pour les ouvertures et trappes.
* `logs/`: Contient les logs de l'application.
* `requirements.txt`: Fichier de spécifications des dépendances du projet.
* `scripts/`: Contient les scripts Python qui executent les tâches de l'application.
* `tests/`: Contient les tests unitaires pour la vérification de la fonctionnalité.

## Architecture Modulaire

L'architecture modulaire est mise en œuvre grâce à des classes et modules séparés. Chaque module a une responsabilité spécifique, ce qui facilite la maintenance et l'évolution du code.
* Les classes `ai_analyzer` et `chess_utils` gèrent l'analyse des échecs.
* La classe `engines` gère l'intégration avec Stockfish.
* Le module `pdf_components` gère la génération de rapports PDF.
* Le module `logger` gère les logs.

## Intégration

L'intégration est réalisée grâce à des imports de modules et classes. Les scripts Python importent les classes et modules nécessaires pour executer les tâches spécifiques.
* Les scripts `chesscom_report.py`, `openings.py` et `traps.py` importent les classes et modules nécessaires pour executer les tâches d'analyse des échecs, de génération de rapports PDF et d'intégration avec Stockfish.

