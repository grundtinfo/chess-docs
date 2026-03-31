# Chess-Docs (Génération de PDF de pièges d'ouverture)

Ce dépôt contient un script Python pour générer un guide PDF des 20 pièges d'ouverture aux échecs (diagrammes + coups commentés).

## 📦 Prérequis

- Python 3.8+ (ou 3.12 déjà présent dans l'environnement `bin/`)
- `pip` install

## 🔧 Installer l'environnement

1. Activer le virtualenv existant :

   ```bash
   source bin/activate
   ```

2. Installer les dépendances :

   ```bash
   pip install -r requirements.txt
   ```

## 🚀 Générer le PDF

Le script principal est : `scripts/11_traps.py`

Pour générer le PDF par défaut (`Guide_Complet_20_Pieges.pdf`) :

```bash
python scripts/11_traps.py
```

Si vous souhaitez appeler la fonction depuis un autre module et personnaliser le nom de sortie :

```python
from scripts import 11_traps  # ou importer le bon module selon votre structure

11_traps.generer_pdf("Mon_PDF_Pieges.pdf")
```

## 📄 Résultat

- Fichier généré : `Guide_Complet_20_Pieges.pdf` (ou nom personnalisé)
- Le script construit :
  - 2 diagrammes Lichess par piège (`fen_alerte`, `fen_final`, `fleches`)
  - tableau détaillé des coups avec commentaires

## 🔎 Détails du script

- `telecharger_echiquier_lichess(fen, orientation, fleches)` : récupère image PNG via l'API Lichess.
- `generer_pdf(nom_fichier)` : crée un fichier PDF avec ReportLab, insère images + tableaux et nettoie les fichiers temporaires.

## ⚠️ Notes

- Si l’accès à internet est coupé, la génération des diagrammes échouera car le script dépend de Lichess pour les captures d’écran.
- `requirements.txt` contient `reportlab`.

## 🛠️ Débogage

- Erreur d'import `reportlab` -> réinstaller : `pip install reportlab`
- Si le PDF n’est pas généré malgré l’exécution, vérifier les logs et l’accès réseau vers `https://lichess1.org/export/fen.png`.
