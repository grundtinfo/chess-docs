#!/usr/bin/env python3
"""
Script pour télécharger et configurer Stockfish localement.
Ce script télécharge le binaire Stockfish précompilé et le configure
pour utilisation avec le package Python stockfish.
"""

import os
import sys
import platform
import shutil
import tarfile
import zipfile
import urllib.request
import subprocess
from pathlib import Path

def get_stockfish_url():
    """Retourne l'URL de téléchargement de Stockfish basée sur l'OS et l'architecture."""
    import tarfile
    import zipfile
    
    machine = platform.machine()
    system = platform.system()
    
    # Version 18 de Stockfish (dernière stable - 2026)
    base_url = "https://github.com/official-stockfish/Stockfish/releases/download/sf_18"
    
    if system == "Linux":
        if machine == "x86_64":
            return f"{base_url}/stockfish-ubuntu-x86-64-avx2.tar"
        elif machine == "aarch64":
            return f"{base_url}/stockfish-ubuntu-aarch64.tar"
        else:
            return f"{base_url}/stockfish-ubuntu-x86-64-sse41-popcnt.tar"
    
    elif system == "Darwin":  # macOS
        if machine == "arm64":
            return f"{base_url}/stockfish-macos-m1-apple-silicon.tar"
        else:
            return f"{base_url}/stockfish-macos-x86-64-avx2.tar"
    
    elif system == "Windows":
        if machine == "AMD64" or machine == "x86_64":
            return f"{base_url}/stockfish-windows-x86-64-avx2.zip"
        else:
            return f"{base_url}/stockfish-windows-armv8.zip"
    
    else:
        raise RuntimeError(f"Système non supporté: {system}")

def download_stockfish():
    """Télécharge et extrait le binaire Stockfish."""
    stockfish_dir = Path.home() / "stockfish"
    stockfish_dir.mkdir(exist_ok=True)
    
    url = get_stockfish_url()
    filename = url.split("/")[-1]
    filepath = stockfish_dir / filename
    
    print(f"📥 Téléchargement de Stockfish depuis: {url}")
    print(f"   Architecture détectée: {platform.system()} {platform.machine()}")
    
    try:
        urllib.request.urlretrieve(url, filepath, reporthook=download_progress)
        print(f"\n✓ Téléchargement réussi: {filepath}")
        
        # Extraire l'archive
        print(f"📦 Extraction de l'archive...")
        if filename.endswith('.tar'):
            with tarfile.open(filepath, 'r') as tar:
                tar.extractall(path=stockfish_dir)
        elif filename.endswith('.zip'):
            with zipfile.ZipFile(filepath, 'r') as zip_ref:
                zip_ref.extractall(path=stockfish_dir)
        
        print(f"✓ Archive extraite")
        
        # Trouver le binaire
        stockfish_bin = find_stockfish_binary(stockfish_dir)
        if stockfish_bin:
            print(f"✓ Binaire trouvé: {stockfish_bin}")
            return stockfish_bin
        else:
            print(f"✗ Binaire Stockfish non trouvé dans l'archive")
            return None
            
    except Exception as e:
        print(f"\n✗ Erreur lors du téléchargement: {e}")
        return None

def find_stockfish_binary(search_dir):
    """Recherche le binaire Stockfish dans un répertoire."""
    # Parcourir les fichiers à la recherche de 'stockfish' ou 'stockfish.exe'
    for root, dirs, files in os.walk(search_dir):
        for file in files:
            # Chercher le binaire exact (pas les archives ou doc)
            if (file.startswith("stockfish-ubuntu") or 
                file.startswith("stockfish-macos") or
                file.startswith("stockfish-windows") or
                file == "stockfish" or 
                file == "stockfish.exe"):
                filepath = Path(root) / file
                # S'assurer que c'est exécutable ou que c'est le bon fichier
                if filepath.is_file() and not str(filepath).endswith(('.tar', '.zip')):
                    return filepath
    return None

def download_progress(block_num, block_size, total_size):
    """Callback pour afficher la progression du téléchargement."""
    downloaded = block_num * block_size
    if total_size > 0:
        percent = min(100, int(100 * downloaded / total_size))
        print(f"\r   Progression: {percent}%", end="")

def make_executable(filepath):
    """Rend le fichier exécutable sur Linux/macOS."""
    if filepath and platform.system() != "Windows":
        try:
            os.chmod(filepath, 0o755)
            print(f"✓ Permissions exécutables définies")
        except Exception as e:
            print(f"⚠️  Impossible de définir les permissions: {e}")

def test_stockfish(stockfish_path):
    """Teste que Stockfish fonctionne correctement."""
    if not stockfish_path:
        return False
        
    print(f"🧪 Test de Stockfish...")
    try:
        result = subprocess.run([str(stockfish_path), "--version"], 
                              capture_output=True, timeout=5, text=True)
        
        if result.returncode == 0:
            version = result.stdout.strip().split("\n")[0]
            print(f"✓ Stockfish fonctionnelle: {version}")
            return True
        else:
            print(f"✗ Stockfish retourné un erreur: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print(f"✗ Timeout lors du test de Stockfish")
        return False
    except Exception as e:
        print(f"✗ Erreur lors du test: {e}")
        return False

def configure_stockfish_path(stockfish_path):
    """Configure le chemin de Stockfish pour le package Python."""
    stockfish_path_str = str(stockfish_path)
    
    # Pour les fichiers openings.py et traps.py, ajouter une configuration
    config_lines = f'''
# Configuration de Stockfish
STOCKFISH_PATH = "{stockfish_path_str}"
'''
    
    print(f"\n📝 Configuration à ajouter à vos scripts:")
    print(f"   Ajouter cette ligne dans vos fichiers Python:")
    print(f"   ```python")
    print(f"   # Dans la classe StockfishAnalyzer, méthode get_engine():")
    print(f"   self.engine = Stockfish(path='{stockfish_path_str}', depth=15, ...")
    print(f"   ```")
    
    # Create a symbolic link in /usr/local/sbin
    try:
        os.symlink(stockfish_path_str, "/usr/local/sbin/stockfish")
        print("\n✓ Lien symbolique créé avec succès.")
    except PermissionError:
        print(f'créer l\'accès à stockfish via cette commande :\n    sudo ln -s {stockfish_path_str} /usr/local/sbin/stockfish')
    except FileExistsError:
        print(f"\n⚠️  Le lien symbolique existe déjà. Vérifiez /usr/local/sbin/stockfish")
    except Exception as e:
        print(f"\n✗ Échec de la création du lien symbolique: {e}")
    
    return stockfish_path_str

def main():
    """Fonction principale."""
    print("=" * 60)
    print("  Installation de Stockfish pour Chess-Docs")
    print("=" * 60)
    print()
    
    # Vérifier que stockfish package est installé
    try:
        import stockfish
        print("✓ Package stockfish trouvé")
    except ImportError:
        print("✗ Package stockfish non trouvé. Installé'il avec:")
        print("   pip install stockfish")
        return 1
    
    # Télécharger Stockfish
    stockfish_path = download_stockfish()
    if not stockfish_path:
        return 1
    
    # Rendre exécutable
    make_executable(stockfish_path)
    
    # Tester
    if not test_stockfish(stockfish_path):
        print("\n⚠️  Avertissement: Stockfish n'a pas pu être testé")
        print("   Vérifiez que le binaire a bien été téléchargé")
    
    # Configurer le chemin
    stockfish_abs_path = configure_stockfish_path(stockfish_path.resolve())
    
    # Instructions finales
    print()
    print("=" * 60)
    print("  ✓ Installation complétée!")
    print("=" * 60)
    print()
    print("📋 Prochaines étapes:")
    print("   1. Vérifier que Stockfish fonctionne:")
    print(f"      /usr/local/sbin/stockfish")
    print()
    print("   2. Les fichiers openings.py et traps.py vont")
    print("      automatiquement détecter Stockfish")
    print()
    print("   3. Relancer la génération des PDFs avec analyse Stockfish")
    print()
    print("   cd ../scripts")
    print("   python3 openings.py")
    print("   python3 traps.py")
    print()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
