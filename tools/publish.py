"""Publish the mod to its Steam Workshop item with SteamCMD.

Copies the mod content (the same items as sync_vanilla.py --deploy) to a clean upload folder, writes a SteamCMD
workshop item file for the existing Workshop item (remote_file_id in descriptor.mod) and runs SteamCMD.
Only the content and a change note are sent: the Workshop title, description, tags, visibility and picture stay
as they are. Nothing is built or uploaded unless sync_vanilla.py --check passes first, so the Egypt files copied
from vanilla match the installed game.

SteamCMD must be logged in once by hand (password and Steam Guard); it then remembers the login.

Usage:
  python tools/publish.py --login                         log SteamCMD in (you type the password and Steam Guard code)
  python tools/publish.py --note "Updated for CK3 1.20"   upload with this change note
  python tools/publish.py --note-file notes.txt           take the change note from a file (Steam BBCode works)
  python tools/publish.py --dry-run                       build the upload folder and item file, upload nothing
  python tools/publish.py --compatch --note "..."         publish the EPE compatch (compatches/epe) instead. The
                                                          first time, this CREATES its Workshop item (public, with
                                                          title, description.txt and thumbnail.jpg) and writes the
                                                          new remote_file_id into compatches/epe/descriptor.mod
  --steamcmd PATH   steamcmd.exe (default: $STEAMCMD, else steamcmd/steamcmd.exe next to the repo folder)
  --user NAME       Steam account name (default: $STEAM_USER, else the most recent account of the Steam client)
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ folder in the repo
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sync_vanilla import (CULTURE, COMPATCH, COMPATCH_ITEMS, DEFAULT_GAME, DEPLOY_ITEMS, MOD, encode,  # noqa: E402
                          epe_dir, game_version, read_text)

APP_ID = "1158310"  # Crusader Kings III
DEFAULT_STEAMCMD = MOD.parent / "steamcmd" / "steamcmd.exe"
UPLOAD_DIR = Path(tempfile.gettempdir()) / "coptic-culture-workshop"


def descriptor_value(text, key):
    m = re.search(rf'(?m)^{key}="([^"]*)"', text)
    return m.group(1) if m else None


def steam_account(game):
    """AccountName of the most recent login of the Steam client, if it can be found."""
    steam_root = game.parents[3]  # .../Steam/steamapps/common/Crusader Kings III/game
    try:
        users, _, _ = read_text(steam_root / "config/loginusers.vdf")
    except OSError:
        return None
    blocks = re.findall(r'"\d+"\s*\{(.*?)\}', users, re.S)
    recent = [b for b in blocks if re.search(r'"MostRecent"\s*"1"', b)]
    # Without a most recent account, only guess when there is a single one
    for block in recent or (blocks if len(blocks) == 1 else []):
        name = re.search(r'"AccountName"\s*"([^"]+)"', block)
        if name:
            return name.group(1)
    return None


def vdf_string(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\r\n", "\n").replace("\n", "\\n") + '"'


def egypt_files_in_sync(game):
    """sync_vanilla.py --check: the vanilla-derived Egypt files must match the installed game."""
    check = subprocess.run([sys.executable, str(Path(__file__).with_name("sync_vanilla.py")), "--check", "--game", str(game)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(check.stdout + check.stderr, end="")
    return check.returncode == 0


def build_upload(content, root=MOD, items=DEPLOY_ITEMS):
    if content.exists():
        shutil.rmtree(content)
    content.mkdir(parents=True)
    for item in items:
        src = root / item
        if src.is_dir():
            shutil.copytree(src, content / item)
        elif src.is_file():
            shutil.copy2(src, content / item)
        else:
            print(f"note: {item} does not exist, not uploaded")
    files = [p for p in content.rglob("*") if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--note", help="change note shown on the Workshop page")
    parser.add_argument("--note-file", type=Path, help="read the change note from this file")
    parser.add_argument("--dry-run", action="store_true", help="build the upload folder and item file only")
    parser.add_argument("--login", action="store_true", help="log SteamCMD in, typing the password yourself")
    parser.add_argument("--steamcmd", type=Path, default=Path(os.environ.get("STEAMCMD", DEFAULT_STEAMCMD)))
    parser.add_argument("--user", default=os.environ.get("STEAM_USER"))
    parser.add_argument("--game", type=Path, default=Path(os.environ.get("CK3_GAME_DIR", DEFAULT_GAME)))
    parser.add_argument("--compatch", action="store_true", help="publish the EPE compatch (compatches/epe) instead")
    args = parser.parse_args()

    if args.login:
        if not args.steamcmd.is_file():
            sys.exit(f"ERROR: steamcmd.exe not found at {args.steamcmd} (use --steamcmd or STEAMCMD)")
        user = args.user or steam_account(args.game)
        if not user:
            sys.exit("ERROR: could not tell which Steam account to use; pass --user or set STEAM_USER")
        # Interactive: SteamCMD itself asks for the password and the Steam Guard code
        sys.exit(subprocess.run([str(args.steamcmd), "+login", user, "+quit"]).returncode)

    note = args.note_file.read_text(encoding="utf-8").strip() if args.note_file else (args.note or "").strip()
    if not note and not args.dry_run:
        sys.exit("ERROR: give a change note with --note or --note-file")

    root, items = (MOD / COMPATCH, COMPATCH_ITEMS) if args.compatch else (MOD, DEPLOY_ITEMS)
    upload_dir = UPLOAD_DIR.with_name(UPLOAD_DIR.name + "-epe-compatch") if args.compatch else UPLOAD_DIR
    descriptor, d_bom, d_crlf = read_text(root / "descriptor.mod")
    item_id = descriptor_value(descriptor, "remote_file_id")
    if not item_id and not args.compatch:
        sys.exit("ERROR: descriptor.mod has no remote_file_id; create the Workshop item once with the Paradox Launcher")
    if args.compatch and not (epe_dir(args.game) / CULTURE).is_file():
        sys.exit("ERROR: Ethnicities and Portraits Expanded is not installed, so the compatch cannot be checked "
                 "against it; subscribe to it on Steam first")
    if not egypt_files_in_sync(args.game):
        sys.exit("ERROR: not published: the Egypt check failed (see above). If the Egypt files are out of date, "
                 "run python tools/sync_vanilla.py, test the mod, then publish again")
    supported = descriptor_value(descriptor, "supported_version") or "?"
    version = game_version(args.game)
    if not version.startswith(supported.rstrip("*").rstrip(".")):
        print(f'WARNING: descriptor.mod says supported_version="{supported}" but the installed game is {version}')

    content = upload_dir / "content"
    count, size = build_upload(content, root, items)
    vdf = upload_dir / "workshop_item.vdf"
    fields = [("appid", APP_ID), ("publishedfileid", item_id or "0"), ("contentfolder", str(content)),
              ("changenote", note or "(dry run)")]
    if not item_id:
        # a new Workshop item: everything its page needs (later uploads only send content and a change note)
        fields += [("title", descriptor_value(descriptor, "name")),
                   ("description", read_text(root / "description.txt")[0].strip()),
                   ("previewfile", str(root / "thumbnail.jpg")),
                   ("visibility", "0")]  # public
    upload_dir.mkdir(parents=True, exist_ok=True)
    vdf.write_text('"workshopitem"\n{\n' + "".join(f'\t"{k}"\t\t{vdf_string(v)}\n' for k, v in fields) + '}\n',
                   encoding="utf-8")
    name = descriptor_value(descriptor, "name")
    where = f"Workshop item {item_id}" if item_id else "NEW Workshop item, created on upload"
    print(f"{name} {descriptor_value(descriptor, 'version')} ({where}): "
          f"{count} files, {size / 1024 / 1024:.1f} MB in {content}")
    if args.dry_run:
        print(f"dry run: nothing uploaded; item file {vdf}")
        return

    if not args.steamcmd.is_file():
        sys.exit(f"ERROR: steamcmd.exe not found at {args.steamcmd} (use --steamcmd or STEAMCMD)")
    user = args.user or steam_account(args.game)
    if not user:
        sys.exit("ERROR: could not tell which Steam account to use; pass --user or set STEAM_USER")

    # No password prompt: SteamCMD must already remember the login, otherwise it fails fast
    cmd = [str(args.steamcmd), "+@ShutdownOnFailedCommand", "1", "+@NoPromptForPassword", "1",
           "+login", user, "+workshop_build_item", str(vdf), "+quit"]
    print(f"uploading with SteamCMD as {user}...")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    output = []
    for line in proc.stdout:
        print(line, end="")
        output.append(line)
    proc.wait()
    log = "".join(output)

    if re.search(r"(?i)login failure|password|steam guard|two-factor", log) and "Success" not in log:
        sys.exit(f"\nERROR: SteamCMD is not logged in. Log in once by hand, then publish again:\n"
                 f'  "{args.steamcmd}" +login {user} +quit')
    if "ERROR" in log or "Success" not in log:
        sys.exit("\nERROR: the upload did not succeed; see the SteamCMD output above")
    if not item_id:
        # SteamCMD writes the new item's id back into the item file
        m = re.search(r'"publishedfileid"\s*"(\d+)"', vdf.read_text(encoding="utf-8", errors="replace"))
        item_id = m.group(1) if m and m.group(1) != "0" else None
        if not item_id:
            m = re.search(r"(?i)PublishFileID\s*:?\s*(\d{6,})", log)
            item_id = m.group(1) if m else None
        if not item_id:
            sys.exit("\nThe item was created but its id was not found: copy it from the SteamCMD output above into "
                     f'{root / "descriptor.mod"} as remote_file_id="..."')
        descriptor = descriptor.rstrip("\n") + f'\nremote_file_id="{item_id}"\n'
        (root / "descriptor.mod").write_bytes(encode(descriptor, d_bom, d_crlf))
        print(f'\nnew Workshop item {item_id}: written to {root / "descriptor.mod"} (commit it)')
    print(f"\npublished: https://steamcommunity.com/sharedfiles/filedetails/?id={item_id}")
    print(f"change notes: https://steamcommunity.com/sharedfiles/filedetails/changelog/{item_id}")


if __name__ == "__main__":
    main()
