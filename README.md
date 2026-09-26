## Dev

Uninstall all mods.
Delete everything in the `mods` folder in `C:\Users\user\Documents\Paradox Interactive\Crusader Kings III\mod`.
Copy the content in a "Coptic Culture" folder to the `mods` folder.
Uncomment `path` in `Coptic Culture.mod`
Move the `Coptic Culture.mod` file to the `mods` folder.
Start the game and enable the mod.

## After a CK3 patch

Some mod files are copies of vanilla files (Egypt titles, Egypt province history, Egyptian culture history).
Re-sync them with the installed game, keeping the Coptic changes:

```
python tools/sync_vanilla.py --check    # show what would change
python tools/sync_vanilla.py            # rebuild the files
python tools/sync_vanilla.py --deploy   # also copy the mod to the local CK3 mod folder for testing
```

