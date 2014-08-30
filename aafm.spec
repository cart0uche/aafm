# -*- mode: python -*-
a = Analysis(['src/aafm-gui.py'],
             pathex=['/home/trevor/programming/aafm'],
             hiddenimports=[],
             hookspath=None,
             runtime_hooks=None)
pyz = PYZ(a.pure)
exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          name='aafm',
          debug=False,
          strip=None,
          upx=False,
          console=False , icon='icon/aafm.ico')
