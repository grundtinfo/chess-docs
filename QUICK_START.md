# Démarrage rapide - Chess-Docs

## 🎯 En 4 étapes

### Étape 1 : Activer le venv local

```bash
source bin/activate
```

### Étape 2 : Installer les dépendances Python

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Étape 3 : Installer et préparer Ollama

Si Ollama n'est pas encore installé :

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Puis démarrez le serveur :

```bash
ollama serve
```

Et téléchargez le modèle utilisé par le projet :

```bash
ollama pull mistral:7b
```

### Étape 4 : Générer les PDFs

```bash
python scripts/setup_stockfish.py
python scripts/traps.py
python scripts/openings.py
```

---

## ✅ Vérifications rapides

```bash
python -c "import chess, reportlab, stockfish; print('Python deps OK')"
ollama list
```

---

## 🆘 En cas de problème

### Les commentaires IA sont génériques
- Vérifiez que Ollama est lancé
- Vérifiez que le modèle `mistral:7b` est téléchargé

### Stockfish n'est pas utilisé
- Vérifiez que `python scripts/setup_stockfish.py` a bien fini
- Les scripts fonctionnent tout de même avec un fallback

### ImportError sur une dépendance

```bash
source bin/activate
python -m pip install -r requirements.txt
```
