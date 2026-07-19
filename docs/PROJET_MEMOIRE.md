# Architecture du Projet Chess-Docs

## Objectifs Principaux
Le projet Chess-Docs vise à fournir des outils et des analyses pour aider les joueurs d'échecs à améliorer leurs compétences. Les principaux objectifs sont :
1. Analyser des parties de chess.
2. Générer des rapports PDF détaillés.
3. Proposer des suggestions de mouvements et d'analyses.
4. Faciliter l'apprentissage en fournissant des informations sur les ouvertures, les tactiques et les pièges.

## Architecture Actuelle

### Fichiers Clés
1. **classes/ai_analyzer.py**
   - Contient la classe `AIAnalyzer` qui gère les analyses de mouvements et d'ouvertures.
   
2. **classes/chess_utils.py**
   - Offre des utilitaires pour le traitement des échecs, comme la conversion de notations, l'évaluation des positions, etc.

3. **classes/config.py**
   - Gère les configurations du système, y compris les paramètres d'API et les chemins de fichiers.

4. **classes/engines.py**
   - Implémente les gestionnaires pour les moteurs d'échecs comme Stockfish et Ollama.

5. **classes/json_cache.py**
   - Gère le stockage en cache des analyses et des états des parties.

6. **classes/logger.py**
   - Fournit une classe de journalisation pour suivre les activités du système.

7. **scripts/chesscom_report.py**
   - Script principal pour générer des rapports PDF à partir des données de Chess.com.

8. **scripts/openings.py**
   - Gère la récupération et le traitement des ouvertures d'échecs.

9. **scripts/setup_stockfish.py**
   - Script pour installer et configurer Stockfish, un moteur d'échecs open source.

10. **scripts/traps.py**
    - Analyse les pièges dans les parties de chess.

### Structure du Projet
Le projet est organisé en plusieurs répertoires principaux :

- `classes/`: Contient toutes les classes utilisées par le système.
- `json/`: Stocke des fichiers JSON contenant des données sur les ouvertures, les pièges, etc.
- `scripts/`: Contient les scripts Python pour générer des rapports et analyser des parties.
- `tests/`: Contient les tests unitaires pour vérifier la fonctionnalité du système.

## Prochaines Étapes
1. **Amélioration de l'Interface Utilisateur**
   - Ajouter une interface utilisateur graphique pour faciliter l'utilisation des outils.

2. **Intégration d'APIs Externes**
   - Intégrer des APIs pour récupérer des données en temps réel sur les parties et les joueurs.

3. **Optimisation des Analyses**
   - Optimiser les algorithmes d'analyse pour améliorer la vitesse et l'exactitude des résultats.

4. **Tests Automatisés**
   - Écrire plus de tests automatisés pour couvrir tous les aspects du système.
