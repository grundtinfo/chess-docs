# CONTEXT_MAP - Projet chess-docs

## Vue d'ensemble
Ce projet est un outil d'analyse automatisée de parties d'échecs (notamment via Chess.com). Il génère des rapports basés sur l'analyse de Stockfish, incluant la détection d'ouvertures et des commentaires stratégiques.

## Arborescence (Scope principal)
- `scripts/` : Contient la logique métier et les scripts d'exécution.
- `classes/` : Contient les définitions de classes (ex: `AIAnalyzer`).

## Composants et Responsabilités
### 1. `scripts/ai_analyzer.py` (Cœur du système)
- **Responsabilité**: Gestion de l'IA et de l'analyse stratégique.
- **Classe principale**: `AIAnalyzer`.
- **Méthodes clés**: 
    - `query_llm(...)`: Orchestre les appels au modèle.
    - `get_stockfish_theory_summary(...)`: Synthèse de la théorie.
    - `translate_opening_name(...)`: Gestion des traductions français/anglais.
- **Variable critique**: `system_prompt` (définit le comportement de l'IA, doit être formel et factuel).

### 2. `scripts/chess_utils.py`
- **Responsabilité**: Utilitaires de traitement de données d'échecs.
- **Méthodes clés**:
    - `is_raw_opening(...)`: Validation d'ouverture.
    - Fonctions de formatage pour les rapports.

### 3. `scripts/chesscom_report.py`
- **Responsabilité**: Orchestrateur principal.
- **Fonction**: Génération du rapport final (PDF/Tableau).

## Flux de données
1. Récupération des données (via `chesscom_report`).
2. Analyse/Validation (via `chess_utils`).
3. Enrichissement IA (via `ai_analyzer` + `system_prompt`).
4. Rendu final (formatage PDF/Tableau).

## Règles de maintenance pour l'Agent
- **TOUTE modification** structurelle ou ajout de méthode majeure doit être reportée dans ce fichier `CONTEXT_MAP.md`.
- **Avant de coder**, vérifie toujours si la fonction que tu crées existe déjà dans `chess_utils.py`.
- **Référencement**: Ne duplique jamais la logique de traduction présente dans `ai_analyzer.py`.
