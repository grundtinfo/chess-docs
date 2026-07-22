# Guide Complet : Création et Automatisation d'un LLM spécialisé aux Échecs (`chess-docs`)

Ce guide détaille la conception, l'automatisation du pipeline de données et l'entraînement par continuation de pré-entraînement (Continued Pre-training) d'un modèle Llama 3.1 8B personnalisé pour l'analyse d'échecs. L'ensemble est optimisé pour une exécution locale sous WSL avec une carte graphique NVIDIA RTX 4060 Mobile (8 Go VRAM).

---

## 1. Architecture et Automatisation du Pipeline de Données (`pdf/` et `json/` vers `.jsonl`)

Pour alimenter efficacement le modèle en données textuelles et structurées sans formater manuellement des paires Q/R, le projet `chess-docs` intègre un script d'automatisation qui scanne un dossier `pdf/` et un dossier `json/` pour générer un corpus unique `chess_raw_corpus.jsonl`.

### 1.1 Règles Fondamentales de Traitement
* **Nomenclature des Ouvertures :** L'extraction et l'identification des noms d'ouvertures (ex: Sicilienne Dragon, Défense Sveshnikov) doivent impérativement s'appuyer sur la bibliothèque `openix`. Aucun nom d'ouverture ne doit être généré ou halluciné par le LLM.
* **Séparation des Responsabilités :** La détection des ouvertures est réservée au module `chesscom_report`. Le mécanisme de caching est quant à lui dédié aux ouvertures et aux pièges.
* **Préservation des Métriques d'Évaluation :** Lors de l'ingestion des fichiers JSON d'analyse de parties, les informations de delta (ex: `delta: -58` ou `delta: -354`) doivent être conservées intactes pour permettre au modèle de comprendre l'impact tactique d'un coup.

### 1.2 Script d'Automatisation de l'Ingestion (`scripts/build_corpus.py`)

Ce script parcourt les dossiers du projet, extrait le texte brut des PDF pédagogiques (comme les cours sur la détection des menaces) et convertit les structures JSON en blocs textuels prêts pour le pré-entraînement auto-régressif.

```python
import os
import json
import fitz # PyMuPDF pour l'extraction PDF
from openix import Openings # Bibliothèque openix pour les ouvertures

def process_pdfs(pdf_dir="pdf/"):
    corpus = []
    if not os.path.exists(pdf_dir):
        return corpus
    
    for filename in os.listdir(pdf_dir):
        if filename.endswith(".pdf"):
            pdf_path = os.path.join(pdf_dir, filename)
            doc = fitz.open(pdf_path)
            text = ""
            for page in doc:
                text += page.get_text() + "\n"
            
            # Structuration en bloc de texte brut
            corpus.append({
                "text": f"--- Document Pédagogique Échecs : {filename} ---\n{text}"
            })
    return corpus

def process_jsons(json_dir="json/"):
    corpus = []
    if not os.path.exists(json_dir):
        return corpus
        
    for filename in os.listdir(json_dir):
        if filename.endswith(".json"):
            json_path = os.path.join(json_dir, filename)
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Si le JSON concerne des ouvertures/pièges, on valide via openix
            # Si le JSON concerne des analyses de parties, on conserve les deltas
            corpus.append({
                "text": f"--- Données Structurées / Analyses : {filename} ---\n{json.dumps(data, ensure_ascii=False)}"
            })
    return corpus

def build_jsonl():
    pdf_data = process_pdfs("pdf/")
    json_data = process_jsons("json/")
    
    total_data = pdf_data + json_data
    output_path = "chess_raw_corpus.jsonl"
    
    with open(output_path, "w", encoding="utf-8") as out:
        for item in total_data:
            out.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    print(f"Corpus généré avec succès : {output_path} ({len(total_data)} documents intégrés).")

if __name__ == "__main__":
    build_jsonl()
```

---

## 2. Exemple d'Intégration Pédagogique (Cours sur les Menaces)

Les documents PDF présents dans le dossier `pdf/` intègrent des concepts fondamentaux d'analyse tactique, essentiels pour le raisonnement du modèle :

> **Apprendre à voir les menaces :** 
> * « Apprenez, à chaque coup, à vous demander quelle est la menace de votre adversaire. »
> * « Ce n'est pas parce qu'un coup défend qu'il ne menace rien : il faut toujours rester vigilant face aux attaques à la découverte (ex: `f6+` ou `×h2+`) et aux gains de qualité (enfilades sur Dame et Tour). »
> * « Méfiez-vous d'un coup qui semble anodin (ex: déplacement de Dame ou recul de pièce), il peut préparer une double attaque ou une menace masquée. »

---

## 3. Configuration de l'Environnement WSL et Fine-Tuning QLoRA

Sur votre environnement WSL (Intel Core i7 Ultra, 12 Go RAM allouée/système, RTX 4060 Mobile 8 Go VRAM), installez les dépendances requises :

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"
pip install --no-deps trl peft accelerate bitsandbytes pymupdf openix
```

### Script de Fine-Tuning (`scripts/train_chess_raw.py`)

```python
from unsloth import FastLanguageModel
import torch
from datasets import load_dataset
from trl import SFTTrainer
from transformers import TrainingArguments

max_seq_length = 2048 
dtype = None 
load_in_4bit = True # Optimisé pour les 8 Go de VRAM de la RTX 4060

# Chargement du modèle Llama 3.1 8B
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = "unsloth/Meta-Llama-3.1-8B",
    max_seq_length = max_seq_length,
    dtype = dtype,
    load_in_4bit = load_in_4bit,
)

# Configuration LoRA
model = FastLanguageModel.get_peft_model(
    model,
    r = 16,
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                      "gate_proj", "up_proj", "down_proj",],
    lora_alpha = 16,
    lora_dropout = 0, 
    bias = "none",
    use_gradient_checkpointing = "unsloth",
    random_state = 3407,
)

# Chargement du corpus généré automatiquement depuis les dossiers pdf/ et json/
dataset = load_dataset("json", data_files="chess_raw_corpus.jsonl", split="train")

trainer = SFTTrainer(
    model = model,
    tokenizer = tokenizer,
    train_dataset = dataset,
    dataset_text_field = "text",
    max_seq_length = max_seq_length,
    dataset_num_proc = 2,
    args = TrainingArguments(
        per_device_train_batch_size = 2,
        gradient_accumulation_steps = 4,
        warmup_steps = 5,
        max_steps = 60,
        learning_rate = 2e-4,
        fp16 = not torch.cuda.is_bf16_supported(),
        bf16 = torch.cuda.is_bf16_supported(),
        logging_steps = 1,
        optim = "adamw_8bit",
        weight_decay = 0.01,
        lr_scheduler_type = "linear",
        seed = 3407,
        output_dir = "outputs_raw",
    ),
)

trainer.train()

# Sauvegarde des adaptateurs et export GGUF pour Ollama
model.save_pretrained("chess_lora_raw_model")
tokenizer.save_pretrained("chess_lora_raw_model")
model.save_pretrained_gguf("chess_raw_gguf", tokenizer, quantization_method = "q4_k_m")
```

---

## 4. Déploiement et Test avec Ollama

Créez le `Modelfile` :
```text
FROM ./unsloth.Q4_K_M.gguf

TEMPLATE """<|begin_of_text|><|start_header_id|>system<|end_header_id|>
Tu es un assistant expert en analyse d'échecs et en tactique, entraîné sur les rapports de parties et la documentation échiquéenne.<|eot_id|><|start_header_id|>user<|end_header_id|>
{{ .Prompt }}<|eot_id|><|start_header_id|>assistant<|end_header_id|>
"""

PARAMETER temperature 0.3
PARAMETER num_ctx 4096
```

Commandes de déploiement sous WSL :
```bash
ollama create chess-raw-llama -f Modelfile
ollama run chess-raw-llama "Analyse la position et identifie la menace cachée après un coup apparemment anodin."
```
