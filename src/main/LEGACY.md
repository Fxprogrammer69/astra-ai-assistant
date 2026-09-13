# Electron shell is legacy

The default ASTRA launch path is **Python + pywebview**:

```
ASTRA.bat
  → src/brain/desktop.py
```

`src/main/` (Electron) is kept only for:

```
npm run electron:legacy
```

Do not add new features here. Tray icons and global shortcuts (`Alt+Space`, `Ctrl+Shift+A`) exist only in this shell.
