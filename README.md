# ♟️ Chess-Docs

**Générateur de guides PDF pour les pièges et ouvertures aux échecs**

Chess-Docs est un outil Python qui génère des guides PDF d'échecs avec diagrammes, analyses de coups et commentaires pédagogiques.

---

## 🎯 Fonctionnalités

- ✅ Génération automatique de guides PDF
- ✅ Analyse Stockfish avec profondeur configurable explicitement depuis les scripts
- ✅ Support de multiples pièges et ouvertures
- ✅ Diagrammes interactifs avec flèches et annotations
- ✅ Données structurées en JSON
- ✅ Mise en page professionnelle avec ReportLab
- ✅ Support des notations d'échecs (FEN) et conversions FR ↔ EN
- ✅ Environnement Python isolé via un venv local déjà présent dans le dépôt
- ✅ Fallback automatique si Stockfish ou Ollama ne sont pas disponibles

---

## 📋 Prérequis

- Python 3.12 (fourni dans le venv local du projet)
- Terminal Linux / WSL2
- Connexion Internet pour installer les dépendances et télécharger Stockfish / Ollama / le modèle LLM
- Ollama installé localement pour les commentaires générés par IA

---

## 📦 Installation locale

### 1. Activer le venv local

```bash
source bin/activate
```

### 2. Installer les dépendances Python

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Packages principaux utilisés :
- `python-chess` — logique d'échecs et manipulation des positions
- `reportlab` — génération des PDF
- `stockfish` — interface Python avec le moteur Stockfish
- `pillow`, `svglib`, `cairo` — rendu des diagrammes
- `requests`, `ollama` — intégration avec Ollama et requêtes HTTP

### 3. Installer et préparer Ollama

Si Ollama n'est pas encore installé :

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Puis démarrez le serveur :

```bash
ollama serve
```

Dans un autre terminal, téléchargez le modèle utilisé par le projet :

```bash
ollama pull mistral:7b
```

Vérifiez la présence du modèle :

```bash
ollama list
```

---

## 🚀 Utilisation

### 1. Installer Stockfish (optionnel mais recommandé)

```bash
python scripts/setup_stockfish.py
```

### 2. Générer les guides PDF

```bash
python scripts/traps.py
python scripts/openings.py
```

Résultats attendus :
- `guide_pieges_et_defenses.pdf`
- `guide_opening_fried_liever_attack.pdf`
- `guide_opening_sicilian_defense.pdf`

### 3. Consulter les PDFs

Les fichiers générés contiennent :
- 📊 diagrammes des positions clés
- 🔍 analyses de coups via Stockfish (si disponible)
- 💡 commentaires pédagogiques via Ollama
- 🎯 notifications de pièges et tactiques

---

## ⚙️ Configuration actuelle du projet

### Stockfish

La profondeur de calcul est pilotée explicitement depuis les scripts :
- `scripts/openings.py`
- `scripts/traps.py`

La valeur par défaut est `18` et peut être adaptée directement dans les signatures des fonctions principales.

### Ollama

Le modèle LLM utilisé dans ce projet est :
- `mistral:7b`

Il doit être téléchargé localement avec :

```bash
ollama pull mistral:7b
```

---

## 📁 Structure du projet

```text
chess-docs/
├── bin/                           # venv local et exécutables Python
├── include/                       # en-têtes Python
├── json/                          # données structurées
├── scripts/
│   ├── chess_lib.py              # logique commune, Stockfish, Ollama
│   ├── openings.py               # génération des guides d'ouvertures
│   ├── traps.py                  # génération des guides de pièges
│   └── setup_stockfish.py        # installation de Stockfish
├── stockfish/                    # binaire Stockfish local
├── pyvenv.cfg                     # configuration du venv
├── requirements.txt              # dépendances Python
├── README.md
├── QUICK_START.md
└── guide_*.pdf                   # PDFs générés
```

---

## 🐛 Dépannage

### Ollama n'est pas disponible

Les scripts peuvent continuer à fonctionner, mais les commentaires IA seront remplacés par un fallback générique.

### Stockfish n'est pas disponible

Les scripts continuent à s'exécuter avec une analyse de secours.

### ImportError sur un package

```bash
source bin/activate
python -m pip install -r requirements.txt
```

### Le PDF n'est pas généré

Vérifiez :
- ✅ le venv est activé
- ✅ Ollama est lancé si vous voulez des commentaires IA
- ✅ les fichiers JSON existent dans `json/`
- ✅ le répertoire racine est accessible en écriture

---

## 📝 Notes importantes

- Le venv local du projet est déjà présent dans `bin/` ; activez-le avant chaque session.
- Les commentaires IA reposent sur Ollama et le modèle `mistral:7b`.
- Stockfish est optionnel mais recommandé pour une analyse plus riche.
- La génération des PDF peut prendre un peu de temps selon la profondeur Stockfish et le nombre de positions traitées.
