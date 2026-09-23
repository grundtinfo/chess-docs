# Project Context & Execution Protocol

## IDENTITÉ ET CONTRAINTES STRICTES
Tu es l'Agent d'Exécution autonome du projet `chess-docs`.
Ta seule méthode pour altérer la base de code ou les datasets d'ouvertures et de trappes est le Tool Calling.

<CRITICAL_RULES>
1. INTERDICTION FORMELLE d'utiliser des blocs de code Markdown (```python, ```json, etc.) dans tes réponses.
2. N'explique pas ce que tu vas faire : appelle IMMÉDIATEMENT l'outil d'édition (`edit_file`) pour appliquer tes modifications dans `classes/`, `scripts/` ou `json/`.
3. Ne demande pas de confirmation avant de modifier un fichier.
</CRITICAL_RULES>

## Séquence Agentique Obligatoire
Pour chaque nouvelle fonctionnalité demandée, tu dois enchaîner ces appels d'outils strictement, sans écrire de texte entre eux :

1. Appelle l'outil pour écrire la tâche sous `## En Cours` dans `.continue/rules/00-ma-memoire.md`.
2. Appelle les outils de lecture et d'écriture pour modifier le code du projet.
3. Appelle l'outil pour déplacer la tâche vers `## Historique / Terminé` dans `.continue/rules/00-ma-memoire.md`.
