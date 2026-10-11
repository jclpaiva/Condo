"""
build.py - Script de compilação para GestaoCondominio
Cria executável + pastas de suporte
"""
import os
import sys
import shutil
from pathlib import Path
import PyInstaller.__main__

# Diretório do projeto
BASE_DIR = Path(__file__).parent.absolute()

# Script principal
MAIN_SCRIPT = str(BASE_DIR / "Main_Gui.py")

# Arquivos e pastas a incluir no executável
ADDITIONAL_FILES = [
    # Fontes
    (str(BASE_DIR / "Fonts/Segoe UI.ttf"), "."),
    (str(BASE_DIR / "Fonts/Segoe UI Bold.ttf"), "."),
    (str(BASE_DIR / "Fonts/Segoe UI Italic.ttf"), "."),
    (str(BASE_DIR / "Fonts/Segoe UI Bold Italic.ttf"), "."),
]

# Módulos Python do projeto (hiddenimports)
HIDDEN_IMPORTS = [
    'Analisar_csv',
    'Balanco',
    'Balanco_Gui',
    'Bancos',
    'Bancos_Gui',
    'Caixa_Gui',
    'Condominos_Gui',
    'Configuracoes_Gui',
    'Database.py',
    'Dashboard_Gui',
    'Despesas',
    'Despesas_Gui',
    'Docs_Gui',
    'Fim_Ano',
    'Fim_Ano_Gui',
    'Commons',
    'Imprimir_Recibo',
    'Imprimir_Recibos',
    'Logging_utils',
    'Receitas',
    'Receitas_Gui',
    'Report',
    'Report_AI',
    # PyQt6
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    # Bibliotecas externas
    'pandas',
    
    
    # ✅ PyMuPDF (fitz) - CRÍTICO para Docs_Gui
    'fitz',
    '_fitz',  # <-- ADICIONADO: necessário para o binário nativo
    'frontend',
    # Matplotlib para Dashboard
    'matplotlib',
    'matplotlib.backends.backend_qt5agg',
    'matplotlib.figure',
    'matplotlib.pyplot',
    # Pillow para imagens
    'PIL',
    'PIL.Image'
]

def get_fitz_binary():
    """Localiza o binário nativo do PyMuPDF (_fitz*.pyd ou _fitz*.so)"""
    try:
        import fitz
        fitz_dir = Path(fitz.__file__).parent
        # Procurar arquivos como _fitz.cpython-XX-x86_64-linux-gnu.so ou _fitz.cp311-win_amd64.pyd
        candidates = list(fitz_dir.glob("_fitz*.pyd")) + list(fitz_dir.glob("_fitz*.so"))
        if candidates:
            return str(candidates[0]), "."
        else:
            raise FileNotFoundError("Nenhum arquivo _fitz* encontrado no diretório do fitz")
    except Exception as e:
        raise RuntimeError(f"Erro ao localizar binário do PyMuPDF: {e}")

def limpar_diretorios():
    """Remove diretórios de builds anteriores"""
    print("🧹 Limpando builds anteriores...")
    for pasta in ['build', 'dist']:
        pasta_path = BASE_DIR / pasta
        if pasta_path.exists():
            shutil.rmtree(pasta_path)
            print(f"   ✓ {pasta}/ removido")

def criar_estrutura_pastas():
    """Cria estrutura de pastas para distribuição"""
    print("\n📁 Criando estrutura de pastas...")
    dist_path = BASE_DIR / "dist"
    
    # Pastas que devem existir fora do executável
    pastas_externas = ['icons', 'fotos', 'docs', 'corrente', 'historico', 'logs']
    
    for pasta in pastas_externas:
        origem = BASE_DIR / pasta
        destino = dist_path / pasta
        
        if pasta in ['icons', 'fotos', 'docs'] and origem.exists():
            # Copiar icons, fotos e docs
            shutil.copytree(origem, destino, dirs_exist_ok=True)
            print(f"   ✓ {pasta}/ copiado")
        else:
            # Criar pastas vazias para corrente, historico, logs
            destino.mkdir(parents=True, exist_ok=True)
            print(f"   ✓ {pasta}/ criado (vazio)")

def compilar():
    """Compila o executável com PyInstaller"""
    print("\n⚙️  Compilando executável...")
    
    # Argumentos do PyInstaller
    pyinstaller_args = [
        MAIN_SCRIPT,
        "--name", "GestaoCondominio",
        "--windowed",  # Sem console
        "--onedir",    # Criar pasta com executável + dependências
        "--distpath", str(BASE_DIR / "dist"),  # dist/ na raiz
        "--workpath", str(BASE_DIR / "build"),
        "--specpath", str(BASE_DIR),
        "--noconfirm",
        "--clean",
    ]
    
    # Adicionar arquivos de dados
    for src, dest in ADDITIONAL_FILES:
        if os.path.exists(src):
            pyinstaller_args.extend(["--add-data", f"{src}{os.pathsep}{dest}"])
    
    # Adicionar imports ocultos
    for module in HIDDEN_IMPORTS:
        pyinstaller_args.extend(["--hidden-import", module])
    
    # 👇 INCLUIR BINÁRIO NATIVO DO PyMuPDF
    try:
        fitz_bin_src, fitz_bin_dest = get_fitz_binary()
        pyinstaller_args.extend(["--add-binary", f"{fitz_bin_src}{os.pathsep}{fitz_bin_dest}"])
        print(f"   ➕ Binário PyMuPDF incluído: {os.path.basename(fitz_bin_src)}")
    except Exception as e:
        print(f"   ⚠️  Aviso: Não foi possível incluir o binário do PyMuPDF: {e}")
    
    # Adicionar ícone se existir
    icon_path = BASE_DIR / "icons" / "app_icon.ico"
    if icon_path.exists():
        pyinstaller_args.extend(["--icon", str(icon_path)])
    
    # Executar PyInstaller
    PyInstaller.__main__.run(pyinstaller_args)

def criar_readme():
    """Cria arquivo README na pasta dist"""
    print("\n📝 Criando README...")
    
    readme_content = """========================================
 GestaoCondominio - Instruções de Uso
========================================

1. Execute: GestaoCondominio\\GestaoCondominio.exe

2. Estrutura de pastas:
   - GestaoCondominio\\ : Executável e bibliotecas
   - docs\\             : Doccs da aplicação
   - icons\\            : Ícones da aplicação
   - fotos\\            : Fotos dos condóminos
   - corrente\\         : Dados do ano corrente (vazia)
   - historico\\        : Dados de anos anteriores (vazia)
   - logs\\             : Logs da aplicação (vazia)

3. IMPORTANTE: NÃO mova o executável para fora da
   pasta GestaoCondominio\\. Mantenha toda a estrutura
   de pastas intacta.

4. Para criar atalho no desktop:
   - Clique direito em GestaoCondominio.exe
   - Enviar para > Área de trabalho (criar atalho)

========================================
"""
    
    readme_path = BASE_DIR / "dist" / "LEIA-ME.txt"
    readme_path.write_text(readme_content, encoding='utf-8')
    print("   ✓ LEIA-ME.txt criado")

def main():
    """Processo principal de build"""
    print("=" * 60)
    print("🏗️  BUILD - GestaoCondominio")
    print("=" * 60)
    
    try:
        # 1. Limpar builds anteriores
        limpar_diretorios()
        
        # 2. Compilar executável
        compilar()
        
        # 3. Criar estrutura de pastas
        criar_estrutura_pastas()
        
        # 4. Criar README
        criar_readme()
        
        print("\n" + "=" * 60)
        print("✅ BUILD CONCLUÍDO COM SUCESSO!")
        print("=" * 60)
        print(f"\n📦 Localização: {BASE_DIR / 'dist'}")
        print(f"🚀 Executável: dist\\GestaoCondominio\\GestaoCondominio.exe")
        print("\n💡 Para distribuir: Compacte a pasta 'dist' completa em ZIP")
        print("=" * 60)
        
    except Exception as e:
        print("\n" + "=" * 60)
        print("❌ ERRO NO BUILD!")
        print("=" * 60)
        print(f"\n{type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()