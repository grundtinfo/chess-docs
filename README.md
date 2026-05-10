# ♟️ Chess-Docs

**Générateur de guides PDF pour les pièges et ouvertures aux échecs**

Chess-Docs est un outil Python qui crée des documents PDF professionnels et informatifs sur les stratégies d'échecs. Il génère des guides illustrés avec des diagrammes d'échiquier détaillés, des analyses de coups et des commentaires pédagogiques.

---

## 🎯 Fonctionnalités

- ✅ Génération automatique de guides PDF avec diagrammes d'échecs
- ✅ Support de multiples pièges d'ouverture et stratégies
- ✅ Diagrammes interactifs avec fleches et annotations
- ✅ Données structurées en JSON pour faciliter la maintenance
- ✅ Mise en page professionnelle avec ReportLab
- ✅ Support des notations d'échecs (FEN)
- ✅ Environnement Python isolé avec virtualenv

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
- `pillow` — Traitement d'images
- `svglib` — Conversion SVG en images ReportLab
- `requests` — Requêtes HTTP pour l'API Lichess

---

## 🚀 Utilisation

### Générer un guide de pièges

Pour générer le PDF complet des pièges d'ouverture :

```bash
python scripts/traps.py
```

**Résultat :** `Guide_Complet_Pieges.pdf` (dans le répertoire racine)

### Générer un guide des ouvertures

```bash
python scripts/openings.py
```

**Résultat :** `Guide_Ouvertures.pdf` (dans le répertoire racine)

### Utilisation en tant que module

```python
from scripts.traps import generer_pdf

# Générer un PDF avec un nom personnalisé
generer_pdf("Mon_Guide_Pieges.pdf")
```

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
├── json/                          # Données structurées
│   ├── opening_fried_liever_attack.json
│   ├── opening_sicilian_defense.json
│   └── trappes_data.json
├── scripts/
│   ├── openings.py                # Génération de guides d'ouvertures
│   ├── traps.py                   # Génération de guides de pièges
│   └── __pycache__/
├── pyvenv.cfg                     # Configuration du virtualenv
├── requirements.txt               # Dépendances Python
└── README.md                      # Cette documentation
```

### Fichiers de données JSON

- **trappes_data.json** — Contient les définitions de pièges avec FEN, coups et annotations
- **opening_*.json** — Données sur les différentes ouvertures d'échecs

---

## 🔧 Architecture des scripts

### `scripts/traps.py`

Génère un guide PDF complet sur les pièges d'ouverture.

**Classe principale :** `ChessboardFlowable`
- Crée des diagrammes d'échecs vectoriels pour ReportLab
- Supporte les annotations avec fleches et surbrillances

**Fonctions clés :**
- `generer_pdf(nom_fichier)` — Crée le document PDF final
- `charger_donnees_json()` — Charge les données des pièges

### `scripts/openings.py`

Génère un guide PDF sur les stratégies d'ouverture.

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

## 🐛 Troubleshooting

### Erreur : Module `reportlab` non trouvé

```bash
pip install --upgrade reportlab
```

### Erreur : Impossible de télécharger les diagrammes

**Cause :** Problème de connexion ou l'API Lichess est inaccessible

**Solution :**
1. Vérifier votre connexion Internet
2. Vérifier que `https://lichess1.org/export/fen.png` est accessible
3. Vérifier les permissions réseau/pare-feu

### Erreur : Permission refusée pour `bin/activate`

```bash
chmod +x bin/activate
source bin/activate
```

### Le PDF n'est pas généré

Vérifiez :
- ✅ Les fichiers JSON existent dans `json/`
- ✅ Le répertoire racine est accessible en écriture
- ✅ Pas d'erreurs dans les données JSON (syntaxe valide)

---

## 📝 Notes importantes

- **Dépendance Internet :** Les diagrammes sont générés via l'API Lichess. Une connexion Internet est requise.
- **Performance :** La génération d'un guide complet peut prendre quelques secondes selon le nombre de pièges/ouvertures.
- **Virtualenv :** Toujours activer le virtualenv avant de lancer les scripts (`source bin/activate`).

---

## 🔗 Ressources

- [Documentation python-chess](https://python-chess.readthedocs.io/)
- [API Lichess](https://lichess.org/api)
- [ReportLab](https://www.reportlab.com/)
- [Notation FEN](https://en.wikipedia.org/wiki/Forsyth%E2%80%93Edwards_Notation)

---

## 📄 Licence

Ce projet est fourni à titre informatif pour l'étude des stratégies d'échecs.

**Dernière mise à jour :** Mai 2026