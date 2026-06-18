# ♟️ Chess-Docs

**Générateur de guides PDF pour les pièges et ouvertures aux échecs**

Chess-Docs est un outil Python qui crée des documents PDF professionnels et informatifs sur les stratégies d'échecs. Il génère des guides illustrés avec des diagrammes d'échiquier détaillés, des analyses de coups et des commentaires pédagogiques.

---

## 🎯 Fonctionnalités

- ✅ Génération automatique de guides PDF avec diagrammes d'échecs
- ✅ **Analyse moteur d'échecs Stockfish** - Commentaires basés sur l'évaluation en temps réel
- ✅ Support de multiples pièges d'ouverture et stratégies
- ✅ Diagrammes interactifs avec flèches et annotations
- ✅ Données structurées en JSON pour faciliter la maintenance
- ✅ Mise en page professionnelle avec ReportLab
- ✅ Support des notations d'échecs (FEN) et conversions automatiques (FR ↔ EN)
- ✅ Environnement Python isolé avec virtualenv
- ✅ Fallback automatique si Stockfish n'est pas disponible

---

## 📋 Prérequis

- **Python 3.8+** (Python 3.12 fourni dans l'environnement)
- **pip** (gestionnaire de paquets Python)
- Connexion Internet (pour récupérer les diagrammes via l'API Lichess)

---

## 📦 Installation

### 1. Activer l'environnement virtuel

```bash
source bin/activate
```

Vous verrez le préfixe `(chess-docs)` dans votre terminal une fois activé.

### 2. Installer les dépendances

```bash
pip install -r requirements.txt
```

**Packages installés :**
- `python-chess` — Logique d'échecs et manipulation des positions
- `reportlab` — Génération de documents PDF
- `stockfish` — Interface Python avec le moteur d'échecs Stockfish (analyse des coups)
- `pillow` — Traitement d'images
- `svglib` — Conversion SVG en images ReportLab
- `pycairo` — Support du rendu PDF vectoriel
- `requests` — Requêtes HTTP (utilitaires généraux)

---

## 🚀 Utilisation

### Démarrage rapide (3 étapes)

#### Étape 1 : Installer Stockfish (optionnel mais recommandé)
```bash
python3 scripts/setup_stockfish.py
```

Cette étape télécharge et installe le moteur Stockfish pour l'analyse des coups. **Sans cette étape, les commentaires seront générés avec un fallback automatique (voir détails ci-dessous).**

#### Étape 2 : Générer les guides PDF

```bash
# Guide des pièges et défenses
python scripts/traps.py
# Résultat : guide_pieges_et_defenses.pdf (~2.5 MB)

# Guides des ouvertures
python scripts/openings.py
# Résultats : guide_opening_fried_liever_attack.pdf (~717 KB)
#           : guide_opening_sicilian_defense.pdf (~2.5 MB)
```

#### Étape 3 : Consulter les PDFs

Les fichiers PDF générés contiennent :
- 📊 Diagrammes des positions clés
- 🔍 Analyse complète des coups (par Stockfish si installé)
- 💡 Commentaires pédagogiques
- 🎯 Notifications des pièges et tactiques

---

### Analyse avec Stockfish

Quand Stockfish est installé, les commentaires des coups incluent :
- ✅ **Évaluation moteur** : "Coup excellent ! (+0.8 point)"
- ⚠️ **Alertes** : "Coup faible qui détériore la position (-1.2)"
- 📈 **Progression** : "Coup solide et améliorant"

**Sans Stockfish** (fallback automatique) :
- Pattern matching heuristique : "Prend le contrôle du centre"
- Détection de tactiques : "Capture une pièce importante"
- Analyse positionnelle : "Développe le cavalier"

---

## 📁 Structure du projet

```
chess-docs/
├── bin/                           # Exécutables Python et scripts d'activation
│   ├── activate                   # Activation du virtualenv (bash/zsh)
│   ├── python, python3, python3.12
│   └── ...
├── lib/
│   └── python3.12/site-packages/  # Packages installés
├── include/                       # En-têtes C (pour les modules compilés)
├── json/                          # Données structurées
│   ├── opening_fried_liever_attack.json
│   ├── opening_sicilian_defense.json
│   └── trappes_data.json
├── scripts/
│   ├── openings.py                # Génération guides d'ouvertures
│   ├── traps.py                   # Génération guides de pièges
│   ├── setup_stockfish.py         # Installation automatique de Stockfish ⭐
│   └── __pycache__/
├── stockfish/                     # Binaire Stockfish (créé par setup_stockfish.py)
├── pyvenv.cfg                     # Configuration du virtualenv
├── requirements.txt               # Dépendances Python
├── README.md                      # Documentation générale (ce fichier)
├── QUICK_START.md                 # Guide de démarrage rapide (3 étapes) ⭐
├── guide_*.pdf                    # PDFs générés
└── lib64                          # Symlink vers lib (virtualenv)
```

### Fichiers de données JSON

- **trappes_data.json** — Définitions de pièges avec FEN, coups et annotations
- **opening_fried_liever_attack.json** — Variantes de l'attaque "Fried Liver"
- **opening_sicilian_defense.json** — Variantes de la défense Sicilienne

### Fichiers de configuration et documentation ⭐

- **setup_stockfish.py** — Script d'installation automatique du moteur Stockfish
- **QUICK_START.md** — Démarrage en 3 étapes (guide rapide)

---

## 🔧 Architecture des scripts

### Classe `StockfishAnalyzer` (Singleton)

Gère l'instance unique du moteur Stockfish dans toute l'application :

```python
class StockfishAnalyzer:
    def get_engine()         # Récupère ou initialise le moteur
    def analyze_move()       # Analyse un coup (éval avant/après)
    def close()              # Nettoie les ressources
```

**Caractéristiques :**
- ✅ Initialisation lazy (au premier usage)
- ✅ Gestion automatique des erreurs
- ✅ Fallback gracieux si Stockfish n'est pas disponible
- ✅ Libération mémoire propre à la fermeture

### Fonction `generate_move_comment()`

Génère les commentaires intelligents pour chaque coup :

1. **Vérification des annotations** : Priorité aux symboles `!`, `?`, `!!`, `??`, etc.
2. **Analyse Stockfish** : Si disponible, évalue le coup avec le moteur (profondeur 15)
3. **Fallback heuristique** : Analyse textuelle de la position et du type de coup

**Résultats possibles :**
```
"Coup excellent ! Améliore la position (+0.8)."      # Stockfish ✅
"Coup faible qui détériore la position (-1.2)."      # Stockfish ✅
"Prend le contrôle du centre."                         # Fallback
"Capture une pièce ou un pion."                        # Fallback
```

### `scripts/traps.py` - Génération des guides de pièges

Génère un guide PDF complet sur les pièges d'ouverture.

**Classe principale :** `ChessboardFlowable`
- Crée des diagrammes d'échecs vectoriels pour ReportLab
- Supporte les annotations avec flèches (défense/menace)
- Gère les positions invalides avec messages d'erreur clairs

**Fonctions clés :**
- `generer_pdf(nom_fichier)` — Crée le document PDF final
- `charger_donnees_json()` — Charge les données des pièges
- `parse_moves(coups_str)` — Parse les notations FEN/française

### `scripts/openings.py` - Génération des guides d'ouvertures

Structure identique à `traps.py` mais adapté aux ouvertures avec variantes multiples.

**Conversion automatique :**
- Notation française → Notation anglaise (D→Q, C→N, F→B, T→R)
- Gestion des pions promus (ex: D=Q)

---

## 📊 Format des données JSON

### Structure d'un piège

```json
{
  "name": "Fried Liver Attack",
  "fen_alerte": "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 1 5",
  "fen_final": "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 2 5",
  "coups": [
    {"notation": "Nxe5", "description": "Le Cavalier prend en e5..."}
  ]
}
```

---

## ⚙️ Configuration

### Python version

L'environnement utilise Python 3.12 par défaut. Pour vérifier :

```bash
python --version
```

### Packages

Vérifier les packages installés :

```bash
pip list
```

---

## ♟️ Configuration Stockfish

### Installation du moteur Stockfish

Stockfish est optionnel mais recommandé pour une meilleure analyse des coups.

#### Option 1 : Installation automatique (recommandée)

```bash
python3 scripts/setup_stockfish.py
```

Le script détecte automatiquement :
- 🖥️ Votre système d'exploitation (Linux, macOS, Windows)
- 🏗️ Votre architecture (x86-64, ARM64, etc.)
- 📥 Télécharge le binaire officiel (~100 MB)
- ✅ Teste la fonctionnalité
- 📍 Affiche l'emplacement du moteur

#### Option 2 : Installation système

**Linux (Debian/Ubuntu) :**
```bash
sudo apt-get install stockfish
```

**macOS (Homebrew) :**
```bash
brew install stockfish
```

**Windows (Chocolatey) :**
```bash
choco install stockfish
```

#### Option 3 : Manuel

Télécharger depuis [lichess-org/stockfish](https://github.com/lichess-org/stockfish/releases) et placer le binaire dans le PATH.

### Configuration avancée

Modifier les paramètres dans `scripts/openings.py` et `scripts/traps.py` (ligne ~45) :

```python
Stockfish(
    depth=15,              # 10 (rapide) à 20 (précis)
    parameters={
        "Threads": 2,      # Nombre de cores CPU
        "Hash": 256        # Cache mémoire (MB)
    }
)
```

**Recommandations :**
- **Rapide** : `depth=10, Threads=4, Hash=128`
- **Équilibré** (défaut) : `depth=15, Threads=2, Hash=256`
- **Précis** : `depth=20, Threads=8, Hash=512`

### Vérification de l'installation

```bash
# Test du package Python
python3 -c "from stockfish import Stockfish; print('✓ Package OK')"

# Test du binaire Stockfish
python3 -c "from stockfish import Stockfish; s = Stockfish(depth=10); print('✓ Moteur OK')"
```

---

## 🐛 Troubleshooting

### ⚠️ Stockfish : "Moteur non trouvé" ou "No such file"

**Cause :** Le binaire Stockfish n'est pas installé

**Solution :**
```bash
python3 scripts/setup_stockfish.py
```

Les scripts **continueront de fonctionner** sans Stockfish en utilisant l'analyse fallback.

### ⚠️ Les commentaires sont génériques

**Cause :** Stockfish binaire n'est pas disponible

**Vérification :**
```bash
python3 -c "from stockfish import Stockfish; Stockfish(depth=10)"
```

Si une erreur s'affiche → Installer Stockfish (voir ci-dessus)

### ⚠️ ImportError: "No module named 'stockfish'"

**Solution :**
```bash
source bin/activate
pip install -r requirements.txt
```

### ⚠️ Erreur : Module `reportlab` non trouvé

```bash
pip install --upgrade reportlab
```

### ⚠️ Les PDFs prennent trop de temps à générer

**Cause :** Profondeur d'analyse Stockfish trop élevée

**Solution :** Réduire la profondeur dans les scripts :
```python
# Ligne ~45 dans openings.py ou traps.py
Stockfish(depth=10, ...)  # Au lieu de 15
```

### ⚠️ Erreur : Permission refusée pour `bin/activate`

```bash
chmod +x bin/activate
source bin/activate
```

### ⚠️ Le PDF n'est pas généré ou est vide

Vérifiez :
- ✅ Les fichiers JSON existent dans `json/`
- ✅ Le répertoire racine est accessible en écriture
- ✅ Pas d'erreurs JSON (vérifier la syntaxe)
- ✅ Espace disque disponible (~3 MB par PDF)

---

---

## � Ressources et documentation supplémentaire

### Guides inclus

- **QUICK_START.md** — Démarrage en 3 étapes pour les utilisateurs pressés
- **README.md** — Cette documentation complète

### Documentation externe

- [python-chess Documentation](https://python-chess.readthedocs.io/) — Logique d'échecs
- [Stockfish GitHub](https://github.com/lichess-org/stockfish/) — Moteur d'échecs open-source
- [ReportLab Documentation](https://www.reportlab.com/) — Génération PDF
- [Notation FEN](https://en.wikipedia.org/wiki/Forsyth%E2%80%93Edwards_Notation) — Format de position d'échecs

---

## 📝 Notes importantes

- **Stockfish est optionnel** : Les scripts fonctionnent immédiatement, avec ou sans le moteur
- **Performance** : La génération peut prendre quelques secondes (selon le nombre de positions)
- **Virtualenv obligatoire** : Toujours activer avec `source bin/activate` avant de lancer les scripts
- **Connexion Internet** : Requise uniquement pour télécharger le binaire Stockfish (une fois)
- **Mise à jour** : Pour mettre à jour les dépendances : `pip install -r requirements.txt --upgrade`

---

## 🎓 Exemple d'analyse complète

Quand Stockfish est actif et analysant un coup :

```
Position : 1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4

Coup analysé : 4...Nxe4
├─ Évaluation avant : +0.2 (légère avantage blanc)
├─ Coup joué : Nxe4
├─ Évaluation après : -0.1 (léger avantage noir)
└─ Commentaire généré : "Coup solide qui égalise la position."

Moteur : Stockfish 17.1 | Profondeur : 15 | Threads : 2
```

---

---

## ✨ Améliorations futures possibles

- 📊 Graphiques d'évaluation (progression des forces au long de la partie)
- 🌐 Export en formats supplémentaires (HTML, EPUB)
- 🎨 Thèmes de diagrammes personnalisables
- 🔄 Support des variantes d'alternatives en ligne
- 📱 Optimisation pour impressions mobiles

---

## 📄 Licence

Ce projet est fourni à titre informatif pour l'étude des stratégies d'échecs.

**Dernière mise à jour :** Mai 2026

---

## 👤 Auteur

Développé avec ❤️ pour l'analyse d'échecs

**Composants utilisés :**
- Stockfish : Moteur d'échecs open-source (AGPL-3.0)
- python-chess : Logique d'échecs (GPL-3.0)
- ReportLab : Génération PDF (BSD)