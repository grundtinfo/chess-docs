# Guide Complet : Création d'un LLM spécialisé aux Échecs (Llama 3.1 8B)

Ce guide détaille les étapes pour concevoir, entraîner et déployer un modèle LLM personnalisé pour l'analyse échiquéenne, optimisé pour une exécution sur une NVIDIA RTX 4060 Mobile (8 Go VRAM) sous WSL avec Ollama.

## Stratégie et Contraintes Matérielles

Un modèle de 8 milliards de paramètres (Llama 3.1 8B) nécessite environ 16 Go de VRAM pour un entraînement classique. Avec 8 Go de VRAM, l'approche **QLoRA (Quantized Low-Rank Adaptation)** est indispensable. Le modèle de base sera quantifié en 4-bit (occupant ~5-6 Go de VRAM), et seuls de petits adaptateurs (LoRA) seront entraînés.

L'architecture du projet `chess-docs` s'appuie sur une séparation stricte des responsabilités. La détection des ouvertures reste réservée au module `chesscom_report`. Le mécanisme de caching doit être exclusivement appliqué aux ouvertures et aux pièges.

---

## Étape 1 : Préparation et Structuration des Données

Le LLM a besoin de données au format "Instruction - Entrée - Sortie" (souvent structurées en JSONL) pour comprendre comment réagir. Les données actuelles incluent des pièges [cite: 1, 2], des variantes d'ouvertures [cite: 3], et des analyses profondes de parties [cite: 4].

### 1.1 Traitement des JSON (Ouvertures et Pièges)
Les fichiers JSON documentent des séquences précises, comme le Mat du Berger [cite: 1] ou les variantes de la Sicilienne (ex: Dragon, Sveshnikov) [cite: 3].
*   **Règle d'or sur la nomenclature :** L'extraction des noms d'ouvertures doit se faire via la bibliothèque `openix`. Il ne faut en aucun cas laisser le LLM générer ou inventer des noms d'ouvertures de lui-même.
*   **Formatage attendu :** Transformez ces JSON en prompts d'entraînement.
    *   *Instruction :* "Explique comment défendre contre le Piège de la Canne à Pêche."
    *   *Output :* "Ne capturez pas mécaniquement un cavalier en g4 si cela ouvre une colonne vers votre roi. Le coup de défense recommandé est 6. d4 ou 6. Te1 [cite: 1]."

### 1.2 Traitement des Analyses de Parties
Les JSON d'analyses contiennent des évaluations coup par coup (good_moves, blunders) [cite: 4]. 
*   **Règle d'or sur le statut :** Lors de l'intégration de ces structures, assurez-vous de conserver précieusement les informations de `delta` (ex: `delta: -58` ou `delta: -354`) [cite: 4]. Ces métriques sont essentielles pour que le LLM comprenne l'impact d'un coup sur l'évaluation de la position.

### 1.3 Traitement des PDF
Utilisez une bibliothèque comme `PyMuPDF` (`fitz`) ou `pdfplumber` dans le virtualenv pour extraire le texte brut des PDF. Découpez ce texte en "chunks" (morceaux cohérents) et associez-les à des instructions génériques (ex: "Explique les principes de la structure de pions selon le document...").

---

## Étape 2 : Configuration de l'Environnement (WSL)

Dans votre WSL, activez votre virtualenv et installez les dépendances optimisées pour QLoRA. L'utilisation de la bibliothèque `unsloth` est fortement recommandée car elle double la vitesse d'entraînement et réduit massivement l'empreinte VRAM.

```bash
# Installation de PyTorch avec support CUDA
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Installation de Unsloth et des outils HuggingFace
pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"
pip install --no-deps trl peft accelerate bitsandbytes
```

---

## Étape 3 : Le Script de Fine-tuning (Python)

Créez un script `train_chess_llm.py`. Voici la structure détaillée pour charger Llama 3.1 en 4-bit et lancer l'entraînement.

```python
from unsloth import FastLanguageModel
import torch
from datasets import load_dataset
from trl import SFTTrainer
from transformers import TrainingArguments

max_seq_length = 2048 # Adapté pour 8Go VRAM
dtype = None # Auto-détection
load_in_4bit = True # Obligatoire pour la RTX 4060

# 1. Chargement du modèle Llama 3.1 8B (version pré-quantifiée par unsloth pour aller plus vite)
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = "unsloth/Meta-Llama-3.1-8B",
    max_seq_length = max_seq_length,
    dtype = dtype,
    load_in_4bit = load_in_4bit,
)

# 2. Configuration des adaptateurs LoRA
model = FastLanguageModel.get_peft_model(
    model,
    r = 16, # Rang LoRA
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                      "gate_proj", "up_proj", "down_proj",],
    lora_alpha = 16,
    lora_dropout = 0, 
    bias = "none",
    use_gradient_checkpointing = "unsloth",
    random_state = 3407,
)

# 3. Préparation du dataset (supposons que vos données compilées sont dans chess_data.jsonl)
dataset = load_dataset("json", data_files="chess_data.jsonl", split="train")

# Fonction pour formater les prompts selon Llama 3
def format_prompts(examples):
    prompts = []
    for instruction, output in zip(examples["instruction"], examples["output"]):
        prompt = f"<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n{instruction}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n{output}<|eot_id|>"
        prompts.append(prompt)
    return {"text": prompts}

dataset = dataset.map(format_prompts, batched=True)

# 4. Configuration de l'entraînement
trainer = SFTTrainer(
    model = model,
    tokenizer = tokenizer,
    train_dataset = dataset,
    dataset_text_field = "text",
    max_seq_length = max_seq_length,
    dataset_num_proc = 2,
    args = TrainingArguments(
        per_device_train_batch_size = 2,
        gradient_accumulation_steps = 4, # Simule un batch size de 8
        warmup_steps = 5,
        max_steps = 60, # A augmenter selon la taille du dataset
        learning_rate = 2e-4,
        fp16 = not torch.cuda.is_bf16_supported(),
        bf16 = torch.cuda.is_bf16_supported(),
        logging_steps = 1,
        optim = "adamw_8bit",
        weight_decay = 0.01,
        lr_scheduler_type = "linear",
        seed = 3407,
        output_dir = "outputs",
    ),
)

# Lancement de l'entraînement
trainer.train()

# 5. Sauvegarde de l'adaptateur
model.save_pretrained("chess_lora_model")
tokenizer.save_pretrained("chess_lora_model")
```

---

## Étape 4 : Conversion au format GGUF (Pour Ollama)

Une fois l'entraînement terminé, vous possédez les poids LoRA. Pour utiliser le modèle dans Ollama localement, il faut fusionner ces poids avec le modèle de base Llama 3.1 et exporter le tout en GGUF. Unsloth permet de le faire nativement.

Ajoutez ceci à la fin de votre script de training (ou dans un script séparé) :

```python
# Exporte en GGUF quantifié 4-bit (q4_k_m) parfait pour Ollama
model.save_pretrained_gguf("chess_model_gguf", tokenizer, quantization_method = "q4_k_m")
```
Le fichier généré sera un `.gguf` prêt à l'emploi.

---

## Étape 5 : Création du Modelfile et Déploiement sur Ollama

Dans le répertoire où se trouve votre fichier `unsloth.Q4_K_M.gguf` (le nom par défaut de l'export), créez un fichier texte nommé `Modelfile`.

**Contenu du Modelfile :**
```text
FROM ./unsloth.Q4_K_M.gguf

TEMPLATE """<|begin_of_text|><|start_header_id|>system<|end_header_id|>
Tu es un expert international des échecs. Ton rôle est d'analyser les parties, d'expliquer les pièges et de commenter les ouvertures.<|eot_id|><|start_header_id|>user<|end_header_id|>
{{ .Prompt }}<|eot_id|><|start_header_id|>assistant<|end_header_id|>
"""

PARAMETER temperature 0.3
PARAMETER num_ctx 4096
```

**Création du modèle dans Ollama :**
Ouvrez votre terminal WSL et tapez :
```bash
ollama create chess-llama -f Modelfile
```

**Test du modèle en local :**
```bash
ollama run chess-llama "Quelles sont les menaces tactiques du Piège de Sibérie ?"
```

Vous pouvez ensuite facilement requêter `chess-llama` directement depuis vos scripts Python locaux (en appelant l'API localhost:11434 d'Ollama) et profiter du système de cache mis en place pour les requêtes récurrentes d'ouvertures et de pièges.
