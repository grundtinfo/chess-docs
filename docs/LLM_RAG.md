# Architecture LLM et RAG pour `chess-docs`
Ce document décrit l’architecture réellement présente dans le projet et une évolution possible vers un système RAG avec un LLM standard et une base vectorielle.

## 1. Architecture actuelle
Le projet n’est pas actuellement un système de fine-tuning Llama complet. Son pipeline principal est déterministe et s’appuie sur plusieurs composants spécialisés :

```text
Sources Chess.com / JSON d’ouvertures / JSON de pièges
            |
            v
        python-chess
                                    |
                                    v
         Stockfish + caches mémoire et JSON
                                    |
                                    v
    rapports PDF, commentaires, précision, ELO estimé
```

### Composants
- `python-chess` gère les échiquiers, FEN, coups légaux, SAN et UCI.
- `StockfishAnalyzer` centralise le moteur Stockfish, son watchdog, ses caches LRU et les analyses combinées.
- Pour une position et une profondeur données, l’analyse combinée utilise `get_top_moves(1)` lorsque l’API le permet afin de mémoriser ensemble l’évaluation et le meilleur coup.
- `Openix` est prioritaire pour identifier les ouvertures. Un fallback local couvre certaines séquences connues.
- `CacheManager` conserve les analyses persistantes dans des fichiers JSON.
- `AIAnalyzer` produit les commentaires, classe les coups et décrit les motifs tactiques.
- `reportlab` génère les guides d’ouvertures, les guides de pièges et les rapports joueurs.
- `ollama` est présent dans les dépendances, mais le dépôt ne fournit pas actuellement une intégration LLM complète et opérationnelle pour le pipeline principal.

### Stockage actuel
- `json/opening_*.json` : sources des guides d’ouvertures.
- `json/opening/cache_variante_*.json` : caches persistants des variantes d’ouverture.
- `json/cache_traps.json` : cache persistant des pièges.
- `json/player_<nom>/game_<id>.json` : reprise et cache des analyses de parties.
- `json/cache_analyses.json` : cache global de certaines traductions et analyses.

Les caches JSON sont des caches exacts : une position ou une clé connue est retrouvée par correspondance, pas par similarité sémantique.

## 2. Ce qui doit rester déterministe

Un LLM ne doit pas remplacer les calculs échiquéens exacts. Les éléments suivants doivent continuer à venir de `python-chess` ou Stockfish :

- légalité des coups ;
- FEN et reconstruction de position ;
- meilleur coup et évaluation ;
- variantes principales ;
- détection d’un mat ou d’une perte matérielle vérifiable ;
- delta, précision et ELO estimé ;
- nom d’ouverture lorsqu’il est disponible via Openix.

Le LLM peut expliquer un résultat, adapter le niveau de langage, comparer des motifs ou répondre à une question documentaire. Il ne doit pas inventer une variante, une évaluation ou un nom d’ouverture absent des données vérifiées.

## 3. Alternative recommandée : LLM standard + base vectorielle

Une alternative plus souple au fine-tuning consiste à utiliser un LLM standard et à lui fournir uniquement les documents pertinents au moment de la requête.

### 3.1 Préparer Ollama et Llama 3.1 8B

Ollama sert ici de serveur local. Le modèle génératif et le modèle d’embeddings sont séparés : Llama répond aux questions, tandis que le modèle d’embeddings transforme les documents et les requêtes en vecteurs.

```bash
# Installer Ollama selon la distribution utilisée, puis vérifier le service.
ollama --version

# Modèle génératif local utilisé par le RAG.
ollama pull llama3.1:8b

# Modèle d'embeddings. Choisir un modèle multilingue disponible localement
# si le corpus français/anglais le nécessite.
ollama pull nomic-embed-text
```

Le nom du modèle doit être configurable plutôt que dispersé dans le code :

```python
LLM_MODEL = "llama3.1:8b"
EMBED_MODEL = "nomic-embed-text"
OLLAMA_HOST = "http://localhost:11434"
```

Llama 3.1 8B est utilisé pour la rédaction et le raisonnement documentaire, pas pour calculer les coups. Une machine disposant d’environ 12 Go de RAM peut l’exécuter en quantification adaptée, mais la latence dépend fortement du contexte transmis et du backend utilisé.

```text
Documents JSON / PDF / rapports
          |
          v
 Nettoyage + découpage en passages
          |
          v
      Modèle d’embeddings
          |
          v
 Base vectorielle + métadonnées
          |
Question + position calculée par Stockfish
          |
          v
 Recherche hybride : vecteur + filtres exacts
          |
          v
 Prompt contrôlé avec sources
          |
          v
      LLM standard
```

### Base vectorielle locale conseillée

Pour ce projet, une première version peut rester locale :

- `ChromaDB` ou `FAISS` pour un prototype simple ;
- `Qdrant` local si l’on veut des filtres et une API plus robuste ;
- SQLite pour les métadonnées et les clés exactes, en complément de la base vectorielle.

Le choix pragmatique est `Qdrant` local si le volume augmente, ou `ChromaDB` si l’objectif est de limiter l’infrastructure. Une base vectorielle ne remplace pas les caches exacts : elle les complète.

### Modèle d’embeddings

Le corpus étant en français et en anglais, il faut utiliser un modèle multilingue, par exemple un modèle Sentence Transformers multilingue. Les embeddings servent à retrouver :

- des explications de motifs similaires ;
- des variantes d’une même ouverture ;
- des pièges proches par idée tactique ;
- des commentaires pédagogiques de niveau comparable.

La position échiquéenne ne doit pas être représentée uniquement par son texte. Chaque document doit conserver des métadonnées exactes :

```json
{
    "source": "cache_variante_Sicilienne.json",
    "kind": "opening_variant",
    "opening": "Défense Sicilienne",
    "fen": "...",
    "moves_uci": ["e2e4", "c7c5"],
    "depth": 18,
    "stockfish_eval": {"type": "cp", "value": 32},
    "best_move": "g1f3"
}
```

Les champs `fen`, `opening`, `kind`, `depth` et `best_move` permettent de filtrer ou de vérifier les résultats. Le texte vectorisé doit rester une aide à la recherche, pas la source de vérité échiquéenne.

## 4. Pipeline d’indexation proposé

Créer un script dédié, par exemple `scripts/build_vector_index.py`, qui :

1. parcourt `json/opening/`, `json/cache_traps.json` et `json/player_*/` ;
2. convertit chaque analyse en passages courts et lisibles ;
3. ajoute les métadonnées FEN, couleur, ouverture, type de source et profondeur ;
4. calcule les embeddings ;
5. insère ou met à jour les documents dans la base vectorielle ;
6. utilise un identifiant stable basé sur le chemin, le FEN et la version du schéma.

Il faut exclure les fichiers temporaires, les PDF générés et les doublons. Le contenu des analyses doit être normalisé avant indexation, mais les valeurs Stockfish originales doivent être conservées dans les métadonnées.

### 4.1 Format normalisé et embeddings Ollama

Un passage doit mélanger le texte explicatif et les faits utiles à la recherche, sans perdre les métadonnées exactes :

```python
import hashlib
import json
from pathlib import Path

import ollama

EMBED_MODEL = "nomic-embed-text"


def stable_id(document):
    raw = f"{document['source']}|{document.get('fen', '')}|{document['text']}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def make_document(source, opening, fen, text, stockfish_eval=None, best_move=None):
    document = {
        "source": source,
        "kind": "opening_variant",
        "opening": opening,
        "fen": fen,
        "text": text,
        "stockfish_eval": stockfish_eval,
        "best_move": best_move,
    }
    document["id"] = stable_id(document)
    return document


def embed_documents(documents):
    texts = [document["text"] for document in documents]
    response = ollama.embed(model=EMBED_MODEL, input=texts)
    return response.embeddings
```

Pour de gros corpus, traiter les documents par lots et conserver le modèle d’embeddings chargé (`keep_alive`) évite de recharger le modèle à chaque appel. Un index doit aussi enregistrer la version du schéma et du modèle d’embeddings afin de pouvoir être reconstruit après un changement de modèle.

### 4.2 Exemple d’index local avec ChromaDB

ChromaDB n’est pas une dépendance obligatoire du projet actuel. Il peut être ajouté pour un prototype RAG :

```bash
python -m pip install chromadb
```

```python
import json
import chromadb

client = chromadb.PersistentClient(path="json/vector_store")
collection = client.get_or_create_collection(
    name="chess_docs",
    metadata={"embedding_model": EMBED_MODEL, "schema_version": 1},
)

documents = [
    make_document(
        source="cache_variante_sicilienne.json",
        opening="Défense Sicilienne",
        fen="...",
        text="Après e4 c5, le développement du cavalier en f3 prépare ...",
        stockfish_eval={"type": "cp", "value": 32},
        best_move="g1f3",
    )
]
embeddings = embed_documents(documents)


def chroma_metadata(document):
    metadata = {}
    for key, value in document.items():
        if key in {"id", "text"} or value is None:
            continue
        metadata[key] = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
    return metadata

collection.upsert(
    ids=[document["id"] for document in documents],
    documents=[document["text"] for document in documents],
    embeddings=embeddings,
    metadatas=[chroma_metadata(document) for document in documents],
)
```

## 5. Pipeline de requête proposé

Pour une question comme « Pourquoi `13...Ce1` est-il une erreur dans cette variante ? » :

1. analyser la position courante avec Stockfish si nécessaire ;
2. identifier l’ouverture avec Openix ;
3. effectuer une recherche vectorielle sur la question et le contexte de la position ;
4. filtrer par ouverture, FEN ou type de document lorsque ces informations sont connues ;
5. fournir au LLM les résultats Stockfish et les passages récupérés ;
6. demander une réponse qui cite la variante et distingue les faits calculés des explications pédagogiques.

Le prompt devrait imposer des règles simples :

```text
Tu expliques uniquement les données fournies.
Les évaluations Stockfish, les coups légaux, les FEN et les noms d’ouverture sont des faits vérifiés.
Ne propose pas une nouvelle variante comme si elle avait été calculée.
Si les sources sont insuffisantes, indique-le.
Réponds en français et cite la source logique : partie, piège ou variante.
```

### 5.1 Recherche vectorielle

La requête est d’abord vectorisée avec le même modèle que les documents. Les métadonnées peuvent ensuite filtrer les résultats par ouverture ou type de source.

```python
def retrieve_context(question, opening=None, limit=4):
    query_embedding = ollama.embed(
        model=EMBED_MODEL,
        input=question,
    ).embeddings[0]

    where = {"opening": opening} if opening else None
    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=limit,
        where=where,
    )

    passages = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    return list(zip(passages, metadatas))
```

Une recherche vectorielle ne suffit pas pour identifier une position exacte. Pour une position connue, commencer par rechercher le FEN dans les caches JSON ou interroger Stockfish, puis utiliser la recherche vectorielle pour retrouver des explications voisines.

### 5.2 Analyse Stockfish avant l’appel LLM

Le LLM reçoit les résultats déterministes plutôt que de tenter de les reconstituer :

```python
import chess
from classes.engines import StockfishAnalyzer


def chess_context(fen):
    board = chess.Board(fen)
    analyzer = StockfishAnalyzer()
    evaluation, best_move = analyzer._get_cached_analysis(fen)
    return {
        "fen": fen,
        "legal_moves": board.legal_moves.count(),
        "evaluation": evaluation,
        "best_move_uci": best_move,
    }
```

Dans une interface publique, préférer une méthode publique dédiée au lieu d’appeler directement `_get_cached_analysis()`. Le snippet montre le principe : la position, l’évaluation et le meilleur coup viennent de Stockfish, tandis que Llama ne fait que les expliquer.

### 5.3 Appel contrôlé à Llama 3.1 8B

```python
import json
import ollama

LLM_MODEL = "llama3.1:8b"


def answer_question(question, fen, opening=None):
    chess_facts = chess_context(fen)
    sources = retrieve_context(question, opening=opening)
    source_text = "\n\n".join(
        f"Source {index}: {text}\nMétadonnées: {metadata}"
        for index, (text, metadata) in enumerate(sources, start=1)
    )

    prompt = f"""
Question utilisateur : {question}

Faits calculés par Stockfish et python-chess :
{json.dumps(chess_facts, ensure_ascii=False)}

Documents récupérés :
{source_text or "Aucun document pertinent."}

Explique en français, sans inventer de coup, d'évaluation ou de source.
Sépare clairement les faits calculés par Stockfish des explications issues des documents.
Si les données sont insuffisantes, dis-le explicitement.
"""

    response = ollama.chat(
        model=LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Tu es un assistant pédagogique d'échecs. "
                    "Stockfish et python-chess sont les seules sources de vérité tactique."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        options={"temperature": 0.2, "num_ctx": 4096},
    )
    return response.message.content
```

Le paramètre `temperature` bas réduit les variations de formulation, mais ne garantit pas l’exactitude. L’exactitude vient du fait que les coups et évaluations sont calculés avant l’appel à Llama.

## 6. LLM local ou service standard

Le RAG permet de changer de modèle sans réindexer le corpus. Deux options sont possibles :

### LLM local

Ollama peut servir de serveur local pour un modèle généraliste. Il réduit la dépendance à un service externe, mais la qualité et la vitesse dépendent de la mémoire disponible et du modèle choisi.

Vérifier le service avant de lancer le pipeline :

```bash
# Le service Ollama doit répondre sur localhost:11434.
curl http://localhost:11434/api/tags

# Vérifier que les modèles nécessaires sont installés.
ollama list

# Test rapide du modèle génératif.
ollama run llama3.1:8b "Réponds uniquement: modèle disponible."
```

Pour un script Python, `ollama.chat()` et `ollama.embed()` utilisent par défaut ce serveur local. Si Ollama écoute ailleurs, utiliser un client configuré :

```python
import ollama

client = ollama.Client(host="http://localhost:11434")
response = client.chat(
    model="llama3.1:8b",
    messages=[{"role": "user", "content": "Explique le principe d'une fourchette."}],
    options={"temperature": 0.2, "num_ctx": 4096},
)
print(response.message.content)
```

### API d’un LLM standard

Un modèle généraliste accessible par API peut recevoir le contexte récupéré depuis la base vectorielle. Cette option évite le fine-tuning et facilite les mises à jour du corpus. Elle nécessite toutefois de protéger les données personnelles des rapports Chess.com et de contrôler les coûts et les limites de contexte.

Dans les deux cas, Stockfish reste local et le LLM ne reçoit que le contexte utile.

### Confidentialité et limites

- Ne pas indexer automatiquement des identifiants Chess.com, URLs privées ou données personnelles dans un service distant.
- Conserver les rapports et caches locaux en dehors de l’index public.
- Limiter le contexte envoyé à Llama aux passages utiles et aux faits Stockfish nécessaires.
- Journaliser le modèle, la version de l’index et la profondeur Stockfish pour rendre une réponse reproductible.
- Refuser une réponse affirmative lorsqu’aucun passage pertinent ou aucun calcul Stockfish n’est disponible.

## 7. Comparaison avec le fine-tuning

| Approche | Mise à jour des connaissances | Coût initial | Contrôle des faits | Usage conseillé |
|---|---:|---:|---:|---|
| Caches JSON actuels | immédiate | faible | très élevé | calculs et reprise |
| LLM standard + RAG | immédiate après réindexation | moyen | élevé avec métadonnées | explications et recherche |
| Fine-tuning | nécessite un nouvel entraînement | élevé | moyen | style ou format spécialisé |

Pour `chess-docs`, le RAG est préférable au fine-tuning comme prochaine étape. Le corpus change avec les nouvelles parties, variantes et analyses Stockfish ; il est donc plus pratique de réindexer des documents que de réentraîner un modèle.

## 8. Plan d’implémentation progressif

1. stabiliser les caches JSON et leur schéma ;
2. créer un export normalisé `jsonl` des variantes, pièges et parties ;
3. ajouter les métadonnées Stockfish et Openix ;
4. indexer localement avec ChromaDB ou Qdrant ;
5. implémenter une recherche hybride exacte + vectorielle ;
6. ajouter un adaptateur LLM Ollama ou API ;
7. tester les réponses contre des cas connus et refuser les affirmations non sourcées ;
8. mesurer latence, nombre de tokens, qualité des explications et taux de réponses sans source.

Cette architecture conserve les résultats exacts du projet et ajoute une couche documentaire sans rendre le LLM responsable du calcul échiquéen.
