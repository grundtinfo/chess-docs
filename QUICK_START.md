# Démarrage rapide - Stockfish pour Chess-Docs

## 🎯 En 3 étapes

### Étape 1: Installer Stockfish (optionnel mais recommandé)
```bash
cd scripts
python3 setup_stockfish.py
```

### Étape 2: Générer les PDFs
```bash
cd scripts
python3 openings.py   # Génère guide_opening_*.pdf
python3 traps.py      # Génère guide_pieges_et_defenses.pdf
```

### Étape 3: Ouvrir les PDFs
Les fichiers PDF générés contiennent maintenant:
- Analyse complète des coups par Stockfish (si installé)
- Diagrammes des positions
- Commentaires pédagogiques

---

## 📦 Dépendances

Déjà installées:
- `python-chess` - Manipulation des positions
- `reportlab` - Génération PDF
- `stockfish` - Interface avec le moteur (binaire optionnel)

---

## 🔍 Vérifier l'installation

```bash
# Vérifier que Stockfish package est installé
python3 -c "import stockfish; print('✓ Stockfish package OK')"

# Vérifier que le binaire Stockfish fonctionne
python3 -c "from stockfish import Stockfish; Stockfish(depth=10); print('✓ Stockfish binaire OK')"
```

---

## 🆘 Troubleshooting

### Les commentaires sont génériques
→ Stockfish binaire n'est pas installé, c'est normal. Le fallback fonctionne.

### "ImportError: stockfish"
```bash
pip install stockfish
```

### Stockfish trop lent
Réduisez la profondeur dans les scripts (ligne ~30):
```python
Stockfish(depth=10, ...)  # Au lieu de 15
```

---

## 💡 Résumé des changements

| Fichier | Changement |
|---------|-----------|
| `openings.py` | Analyse Stockfish + fallback |
| `traps.py` | Analyse Stockfish + fallback |
| `requirements.txt` | Ajout `stockfish` |
| `setup_stockfish.py` | **NOUVEAU** - Installation Stockfish |
| `STOCKFISH_GUIDE.md` | **NOUVEAU** - Documentation complète |

---

✅ **C'est prêt!** Les scripts utilisent maintenant Stockfish pour analyser les coups.
