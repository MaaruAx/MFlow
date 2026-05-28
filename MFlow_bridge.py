# MFlow_bridge.py  —  NO se usa directamente.
# El launcher es MFlow.lua (Scripts\Utility\MFlow.lua).
# Este archivo existe solo como fallback para correr MFlow desde terminal:
#   python MFlow_bridge.py
import sys, os

HERE = os.path.dirname(os.path.abspath(__file__))
txt = os.path.join(HERE, "mflow_path.txt")

mflow_dir = HERE  # si este archivo esta en la carpeta de MFlow
if os.path.isfile(txt):
    p = open(txt, encoding="utf-8").read().strip()
    if os.path.isfile(os.path.join(p, "main.py")):
        mflow_dir = p

sys.path.insert(0, mflow_dir)

try:
    import main as _m
    _m.main()
except Exception as e:
    import traceback; traceback.print_exc()
    input("\nPresiona Enter para cerrar...")
