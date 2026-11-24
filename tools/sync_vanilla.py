"""Re-sync the mod's copies of vanilla files with the installed CK3 version.

Since CK3 1.21 the game has its own Coptic culture (key remenkimi). The mod builds on it instead of adding a
second one, and four mod files are copies of vanilla files with our changes on top:
  - common/landed_titles/coptic_title.txt    (vanilla k_egypt nested in its empire, plus the Coptic place names)
  - common/culture/name_lists/00_egyptian.txt  (replaces the vanilla file of the same name: the vanilla Coptic
                                              name list, with realms no longer named after the ruling house
                                              and the mod's family names added)
  - common/culture/cultures/00_egyptian.txt  (replaces the vanilla file of the same name: the vanilla Coptic
                                              culture with Byzantine buildings instead of Arab ones and
                                              the mod's own soldiers on the map, gfx/models/units)
  - common/council_tasks/coptic_council_tasks.txt  (a NEW steward task built from the vanilla task_promote_culture,
                                              nothing of vanilla is overridden: "Revive the Coptic Tongue",
                                              2x as fast, shown only while the decision of the same name
                                              is in effect, in counties with the Coptic Revival modifier)

It also builds the compatch with Ethnicities and Portraits Expanded (compatches/epe, a separate small mod): EPE's
own copy of the culture file (its Egyptian faces) with the same two lines of ours, when EPE is installed from the
Workshop; --deploy also copies it to the local mod folder as its own mod.

The Coptic place names are read from the current mod file, so the mod file stays the source of truth:
add a name there (name_list_remenkimi = cn_...), then run this script after each game patch.
The script stops with an error whenever vanilla changed in a way it cannot merge safely.

Usage:
  python tools/sync_vanilla.py            rebuild the files from the installed game
  python tools/sync_vanilla.py --check    only report what would change (exit code 1 if anything would)
  python tools/sync_vanilla.py --deploy   also copy the mod to the local CK3 mod folder for testing
  --game PATH                             CK3 "game" folder (default: $CK3_GAME_DIR or the Steam default)
"""
import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

MOD = Path(__file__).resolve().parent.parent
DEFAULT_GAME = Path(r"C:/Program Files (x86)/Steam/steamapps/common/Crusader Kings III/game")
DEPLOY_DIR = Path.home() / "Documents/Paradox Interactive/Crusader Kings III/mod/Coptic Culture"
DEPLOY_ITEMS = ["common", "history", "localization", "music", "gfx", "descriptor.mod", "thumbnail.png"]

TITLES = "common/landed_titles/coptic_title.txt"
CULTURE = "common/culture/cultures/00_egyptian.txt"
# Compatch with Ethnicities and Portraits Expanded (EPE replaces the same culture file, for its faces): a separate
# small mod in compatches/epe, built from EPE's file when EPE is installed from the Workshop.
EPE_ID = "2507209632"
COMPATCH = "compatches/epe"
COMPATCH_NAME = "Coptic Culture - EPE Compatch"
COMPATCH_ITEMS = ["common", "descriptor.mod", "thumbnail.jpg"]
COMPATCH_DEPLOY_DIR = DEPLOY_DIR.parent / COMPATCH_NAME
KINGDOM = "k_egypt"
CULTURE_KEY = "remenkimi"
NAME_LIST = "name_list_remenkimi"
# The kingdom's vanilla colour on the map. Under a Coptic ruler the mod repaints it bright gold, and back to this
# colour under anyone else (common/scripted_effects/coptic_effects.txt, which repeats these numbers).
KINGDOM_COLOR = "\t\tcolor = { 10 255 80 }"
# The two things the mod changes in the vanilla culture: (vanilla line, our line)
BUILDINGS = ("\tbuilding_gfx = { mena_building_gfx }", "\tbuilding_gfx = { byzantine_building_gfx }")
# Our soldier models come first; fleets, siege engines and courts have no Coptic model and fall back on the Arab ones
SOLDIERS = ("\tunit_gfx = { mena_unit_gfx }", "\tunit_gfx = { coptic_unit_gfx mena_unit_gfx }")

# The vanilla name list of the Coptic culture, with two changes.
NAMES = "common/culture/name_lists/00_egyptian.txt"
# 1. Vanilla shows the realm of a Coptic ruler under his house's name ("...id"), like Arab realms. Then the
#    kingdom of Egypt never shows its Coptic name (Kime) for the very ruler who holds it: turned off.
HOUSE_NAMING = ("\thouse_based_map_names = yes", "\thouse_based_map_names = no")
# 2. Family names the mod had before 1.21, added to the 18 vanilla ones (keys dynn_<name>; their texts are in
#    localization/english/dynasties/coptic_dynasties_l_english.yml unless the game already has the key).
#    Kept: towns of Egypt in the style of the vanilla names (Asyuti, Akhmimi, Qusi), families of Coptic officials
#    and patriarchs of the period (Isa ibn Nasturus, Fahd ibn Ibrahim, Gabriel ibn Turayk), the Apions of
#    Byzantine Egypt, the Bashmurites of the Delta, and Coptic-language names, which vanilla has none of.
#    Left out: doubles (Shanouda, Papnoute, Babnouda, Asyuti), a Muslim name (Abderahman), plain first names and
#    modern surnames (Haroun, Zaia, Bayomi, Quolta), Ruweis (14th century) and Kazzazi (source not found).
FAMILIES = ("Fayyumi", "Dumyati", "Iskandari", "Fustati", "Aswani", "Nasturusi", "Fahdi", "Turayk", "Apion", "Bashmur",
            "Shenouti", "Paphnoutios", "Barsanouphios", "Merkourios", "Amoun")

TITLES_PREAMBLE = """@correct_culture_primary_score = 100
@better_than_the_alternatives_score = 50
@always_primary_score = 1000
@never_primary_score = -1000

# Generated by tools/sync_vanilla.py from CK3 {version} common/landed_titles/00_landed_titles.txt:
# vanilla {kingdom} and the properties of its empire {empire}, with Coptic place names added.
# {kingdom} MUST stay nested in {empire}: a title redefined at the top level of a later
# file loses its de jure liege, which removed Egypt from the Arabian Empire.
# Only the {empire} properties are copied here; its other kingdoms are untouched.
"""


class SyncError(Exception):
    pass


TASK = "common/council_tasks/coptic_council_tasks.txt"
TASK_VANILLA = "common/council_tasks/00_steward_tasks.txt"
TASK_FROM, TASK_KEY = "task_promote_culture", "task_coptic_revive_tongue"
TASK_SHOWN = """		# Coptic Culture mod: only while the decision "Revive the Coptic Tongue" is in effect in the realm
		scope:councillor_liege = {
			coptic_culture_or_descendant_trigger = yes
			any_sub_realm_county = { has_county_modifier = coptic_tongue_revival_modifier }
		}
"""
TASK_COUNTIES = """	potential_county = {
		scope:county = {
			is_landless_type_title = no
			culture != scope:councillor_liege.culture
			# own text: the game has no "does not have this county modifier" wording for this tooltip
			custom_tooltip = {
				text = coptic_tongue_revival_county_tt
				has_county_modifier = coptic_tongue_revival_modifier
			}
		}
	}
"""
TASK_SPEED = """		multiply = {
			value = 2
			desc = COPTIC_REVIVAL_PROMOTE_CULTURE_BONUS
		}
"""
TASK_AI = """	ai_will_do = {
		value = 0
	}
"""
TASK_CONVERT = "\t\t\tset_county_culture = scope:councillor_liege.culture\n"
# our own icon: Coptic alpha and zita on the steward ring (made in work/coptic-3d-tools/task_icon)
TASK_ICON = ('icon = "gfx/interface/icons/council_task_types/task_promote_culture.dds"',
             'icon = "gfx/interface/icons/council_task_types/task_coptic_revive_tongue.dds"')


def read_text(path):
    raw = path.read_bytes()
    return raw.decode("utf-8-sig").replace("\r\n", "\n"), raw.startswith(b"\xef\xbb\xbf"), b"\r\n" in raw


def encode(text, bom, crlf):
    if crlf:
        text = text.replace("\n", "\r\n")
    return (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8")


def game_version(game):
    settings = game.parent / "launcher/launcher-settings.json"
    try:
        return json.loads(settings.read_text(encoding="utf-8"))["rawVersion"]
    except (OSError, KeyError, ValueError):
        return "unknown version"


def block_end(lines, start, indent):
    for i in range(start + 1, len(lines)):
        if lines[i] == indent + "}":
            return i
    raise SyncError(f"unterminated block at line {start + 1}")


def build_titles(game, version):
    """Vanilla empire properties + vanilla k_egypt, with the mod's Coptic place names re-injected."""
    mod_text, _, _ = read_text(MOD / TITLES)
    names = {}
    # A title (its header line may end with a comment), then any lines that are not another title
    # definition, then its cultural_names block
    title_names = (r"\n\t+([bcdk]_[\w-]+) = \{[^\n]*\n(?:(?!\t+[bcdk]_[\w-]+ = \{)[^\n]*\n)*?\t+cultural_names = \{\n\t+"
                   + NAME_LIST + r" = (\w+)")
    for m in re.finditer(title_names, mod_text):
        names[m.group(1)] = m.group(2)
    if not names:
        raise SyncError(f"no Coptic place names ({NAME_LIST} = ...) found in {TITLES}")
    declared = len(re.findall(rf"(?m)^[^#\n]*\b{NAME_LIST}\s*=", mod_text))
    if declared != len(names):
        raise SyncError(f"{TITLES} has {declared} {NAME_LIST} lines but only {len(names)} were understood; "
                        f"put {NAME_LIST} first in its title's own cultural_names block")

    vanilla, _, _ = read_text(game / "common/landed_titles/00_landed_titles.txt")
    lines = vanilla.split("\n")
    k_start = next((i for i, l in enumerate(lines) if l == f"\t{KINGDOM} = {{"), None)
    if k_start is None:
        raise SyncError(f"{KINGDOM} is no longer nested directly in an empire in vanilla; update this script")
    e_start = max(i for i in range(k_start) if re.match(r"^[eh]_\w+ = \{", lines[i]))
    empire = lines[e_start].split(" ")[0]
    first_child = next(i for i in range(e_start + 1, len(lines)) if re.match(r"^\t[kdc]_[\w-]+ = \{", lines[i]))
    header = lines[e_start:first_child]
    while header and not header[-1].strip():
        header.pop()
    kingdom = lines[k_start:block_end(lines, k_start, "\t") + 1]
    if any(NAME_LIST in line.split("#")[0] for line in kingdom):
        raise SyncError(f"vanilla {KINGDOM} now has its own {NAME_LIST} names; compare them with ours and update this script")
    for i, line in enumerate(kingdom):
        m = re.match(r"^(\t+)([bcdk]_[\w-]+) = \{", line)
        if m and m.group(2) in names:
            own = rf"^{m.group(1)}\tcultural_names\s*=\s*\{{"
            if any(re.match(own, l) for l in kingdom[i:block_end(kingdom, i, m.group(1))]):
                raise SyncError(f"vanilla {m.group(2)} now has its own cultural_names; merge {NAME_LIST} into it and update this script")

    out, pending, done = [], None, set()
    for line in kingdom:
        m = re.match(r"^(\t+)([bcdk]_[\w-]+) = \{", line)
        if m and m.group(2) in names:
            pending = (m.group(1), m.group(2))
        if pending and line == pending[0] + "}":
            raise SyncError(f"vanilla {pending[1]} has no {'province' if pending[1].startswith('b_') else 'color'} line of its own; update this script")
        out.append(line)
        if pending:
            indent, key = pending
            anchor = rf"^{indent}\tprovince = \d+" if key.startswith("b_") else rf"^{indent}\tcolor = \{{"
            if re.match(anchor, line):
                out += ["", f"{indent}\tcultural_names = {{", f"{indent}\t\t{NAME_LIST} = {names[key]}", f"{indent}\t}}"]
                done.add(key)
                pending = None
    missing = sorted(set(names) - done)
    if missing:
        raise SyncError(f"titles with Coptic names not found in vanilla {KINGDOM}: {', '.join(missing)}")
    if out[1] != KINGDOM_COLOR:
        raise SyncError(f"vanilla {KINGDOM} no longer starts with '{KINGDOM_COLOR.strip()}'; update this script "
                        "and the colour in common/scripted_effects/coptic_effects.txt")

    preamble = TITLES_PREAMBLE.format(version=version, kingdom=KINGDOM, empire=empire)
    return preamble + "\n" + "\n".join(header) + "\n\n" + "\n".join(out) + "\n}\n"


def merge_culture(text, source, header, base):
    """The Coptic culture file `text` (from `source`), with our buildings and soldier models swapped in."""
    cultures = re.findall(r"(?m)^(\w+) = \{", text)
    if cultures != [CULTURE_KEY]:
        raise SyncError(f"{source} no longer holds only the {CULTURE_KEY} culture (found: {', '.join(cultures)}); "
                        "our file replaces the whole file, so update this script")
    header += f"# Changes from {base}:\n"
    for old, new in (BUILDINGS, SOLDIERS):
        if text.count(old + "\n") != 1:
            raise SyncError(f"{source} has no '{old.strip()}' line any more; update this script")
        text = text.replace(old + "\n", new + "\n")
        header += f"#   {new.strip()}   ({base}: {old.strip()})\n"
    return header + text


def build_culture(game, version):
    """The vanilla Coptic culture, unchanged except for the look of its buildings and of its armies on the map."""
    vanilla, _, _ = read_text(game / CULTURE)
    return merge_culture(vanilla, f"vanilla {CULTURE}",
                         f"# Generated by tools/sync_vanilla.py: replaces vanilla {CULTURE} (CK3 {version}).\n", "vanilla")


def epe_dir(game):
    """The installed Workshop copy of Ethnicities and Portraits Expanded (game = .../steamapps/common/CK3/game)."""
    return game.parents[2] / "workshop" / "content" / "1158310" / EPE_ID


def build_epe_culture(game, version):
    """Compatch with EPE: EPE's Coptic culture (its faces), plus our buildings and soldier models."""
    epe, _, _ = read_text(epe_dir(game) / CULTURE)
    return merge_culture(epe, f"EPE's {CULTURE}",
                         f"# Generated by tools/sync_vanilla.py: Coptic Culture + Ethnicities and Portraits Expanded.\n"
                         f"# EPE's {CULTURE} (its Egyptian faces), with the Coptic Culture mod's two lines (CK3 {version}).\n"
                         "# Load this compatch after both mods.\n", "EPE")


def build_names(game, version):
    """The vanilla Coptic name list: realms not named after the house, and the mod's family names added."""
    vanilla, _, _ = read_text(game / NAMES)
    lists = re.findall(r"(?m)^(\w+) = \{", vanilla)
    if lists != [NAME_LIST]:
        raise SyncError(f"vanilla {NAMES} no longer holds only {NAME_LIST} (found: {', '.join(lists)}); "
                        "our file replaces the whole vanilla file, so update this script")
    old, new = HOUSE_NAMING
    if vanilla.count(old + "\n") != 1:
        raise SyncError(f"vanilla {NAMES} has no '{old.strip()}' line any more; update this script")
    text = vanilla.replace(old + "\n", new + "\n")
    for block in ("cadet_dynasty_names", "dynasty_names"):
        m = re.search(rf"(?m)^\t{block} = \{{\n(.*?)^\t\}}\n", text, flags=re.S)
        if not m:
            raise SyncError(f"vanilla {NAMES} has no '{block}' list any more; update this script")
        have = set(re.findall(r'"dynn_([^"]+)"', m.group(1)))
        ours = "".join(f'\t\t"dynn_{n}"\n' for n in FAMILIES if n not in have)
        text = text[:m.end(1)] + ours + text[m.end(1):]
    header = (f"# Generated by tools/sync_vanilla.py: replaces vanilla {NAMES} (CK3 {version}).\n# Changes from vanilla:\n"
              f"#   {new.strip()}   (vanilla: {old.strip()}), so the kingdom of Egypt keeps its Coptic name under a Coptic ruler\n"
              f"#   {len(FAMILIES)} family names of the mod added after the vanilla ones in both lists\n")
    return header + text


def replace_section(block, name, new):
    """Replace the top-level section `name = { ... }` of a council task block."""
    m = re.search(rf"(?m)^\t{name} = \{{\n", block)
    if not m:
        raise SyncError(f"vanilla {TASK_FROM} has no '{name}' section any more; update this script")
    lines = block[:m.start()].count("\n")
    all_lines = block.split("\n")
    stop = block_end(all_lines, lines, "\t")
    return "\n".join(all_lines[:lines]) + "\n" + new + "\n".join(all_lines[stop + 1:])


def build_task(game, version):
    """A new steward task: the vanilla Promote Culture task, twice as fast, only in Coptic Revival counties."""
    vanilla, _, _ = read_text(game / TASK_VANILLA)
    m = re.search(rf"(?ms)^{TASK_FROM} = \{{\n.*?^\}}\n", vanilla)
    if not m:
        raise SyncError(f"vanilla {TASK_VANILLA} has no '{TASK_FROM}' any more; update this script")
    block = TASK_KEY + m.group(0)[len(TASK_FROM):]
    if block.count("\tis_shown = {\n") != 1 or block.count(TASK_CONVERT) != 1 or block.count(TASK_ICON[0]) != 1:
        raise SyncError(f"vanilla {TASK_FROM} changed shape (is_shown, set_county_culture or icon); update this script")
    block = block.replace(*TASK_ICON)
    block = block.replace("\tis_shown = {\n", "\tis_shown = {\n" + TASK_SHOWN, 1)
    block = replace_section(block, "potential_county", TASK_COUNTIES)
    block = replace_section(block, "ai_will_do", TASK_AI)
    # the speed: multiply the whole vanilla progress at its very end
    lines = block.split("\n")
    i = lines.index("\tprogress = {")
    stop = block_end(lines, i, "\t")
    block = "\n".join(lines[:stop]) + "\n" + TASK_SPEED + "\n".join(lines[stop:])
    # a converted county no longer needs the marker
    block = block.replace(TASK_CONVERT, TASK_CONVERT + "\t\t\tremove_county_modifier = coptic_tongue_revival_modifier\n")
    header = (f"# Generated by tools/sync_vanilla.py from {TASK_FROM} in {TASK_VANILLA} (CK3 {version}).\n"
              f"# A new task, {TASK_KEY}; vanilla is not overridden. Changes from the vanilla task:\n"
              "#   is_shown: also needs a Coptic liege with a Coptic Revival county (decision \"Revive the Coptic Tongue\")\n"
              "#   potential_county: only counties with the Coptic Revival modifier and another culture\n"
              "#   progress: x2 at the end\n"
              "#   on finish: also removes the Coptic Revival modifier\n"
              "#   ai_will_do: 0 (the AI does not use it)\n"
              "#   icon: our own (Coptic alpha and zita)\n")
    return header + block


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, default=Path(os.environ.get("CK3_GAME_DIR", DEFAULT_GAME)))
    parser.add_argument("--check", action="store_true", help="report changes without writing (exit 1 if any)")
    parser.add_argument("--deploy", action="store_true", help=f"also copy the mod to {DEPLOY_DIR}")
    args = parser.parse_args()

    if not (args.game / "common/landed_titles/00_landed_titles.txt").is_file():
        sys.exit(f"CK3 game folder not found: {args.game} (use --game or CK3_GAME_DIR)")
    version = game_version(args.game)
    print(f"CK3 {version} at {args.game}")

    changed = []
    builds = [(TITLES, build_titles), (CULTURE, build_culture), (NAMES, build_names), (TASK, build_task)]
    if (epe_dir(args.game) / CULTURE).is_file():
        builds.append((f"{COMPATCH}/{CULTURE}", build_epe_culture))
    else:
        print(f"NOTE: Ethnicities and Portraits Expanded is not installed: the EPE compatch was not rebuilt")
    try:
        for rel, build in builds:
            path = MOD / rel
            _, bom, crlf = read_text(path) if path.is_file() else ("", True, False)
            new = encode(build(args.game, version), bom, crlf)
            if not path.is_file() or new != path.read_bytes():
                changed.append(rel)
                if not args.check:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(new)
    except SyncError as e:
        sys.exit(f"ERROR: {e}")

    verb = "would change" if args.check else "updated"
    print(f"{verb}: {', '.join(changed)}" if changed else "already in sync with vanilla")

    descriptor, _, _ = read_text(MOD / "descriptor.mod")
    supported = re.search(r'supported_version="([\d.]+)', descriptor)
    if supported and not version.startswith(supported.group(1).rstrip(".")):
        print(f'NOTE: descriptors say supported_version="{supported.group(1)}*" but the game is {version}; '
              "update both descriptor.mod and Coptic Culture.mod")

    if args.deploy and not args.check:
        DEPLOY_DIR.mkdir(parents=True, exist_ok=True)
        for item in DEPLOY_ITEMS:
            src, dst = MOD / item, DEPLOY_DIR / item
            if src.is_dir():
                shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(src, dst)
            elif src.is_file():
                shutil.copy2(src, dst)
            else:                       # the mod no longer has this folder: drop the old copy
                shutil.rmtree(dst, ignore_errors=True)
        # The launcher reads the .mod file next to the mod folder (it holds the local path): keep its versions in step
        launcher_mod = DEPLOY_DIR.parent / "Coptic Culture.mod"
        if launcher_mod.is_file():
            text, bom, crlf = read_text(launcher_mod)
            for key in ("version", "supported_version"):
                line = re.search(rf'(?m)^{key}="[^"]*"', descriptor)
                if line:
                    text = re.sub(rf'(?m)^{key}="[^"]*"', line.group(0), text)
            launcher_mod.write_bytes(encode(text, bom, crlf))
        print(f"deployed to {DEPLOY_DIR}")
        # the EPE compatch, as its own local mod (the launcher lists it from its .mod file)
        shutil.rmtree(COMPATCH_DEPLOY_DIR, ignore_errors=True)
        COMPATCH_DEPLOY_DIR.mkdir(parents=True)
        for item in COMPATCH_ITEMS:
            src = MOD / COMPATCH / item
            if src.is_dir():
                shutil.copytree(src, COMPATCH_DEPLOY_DIR / item)
            elif src.is_file():
                shutil.copy2(src, COMPATCH_DEPLOY_DIR / item)
        text, bom, crlf = read_text(MOD / COMPATCH / "descriptor.mod")
        text = re.sub(r'(?m)^path="[^"]*"\n?', "", text).rstrip("\n") + f'\npath="{COMPATCH_DEPLOY_DIR.as_posix()}"\n'
        (DEPLOY_DIR.parent / f"{COMPATCH_NAME}.mod").write_bytes(encode(text, bom, crlf))
        print(f"deployed to {COMPATCH_DEPLOY_DIR}")

    if args.check and changed:
        sys.exit(1)


if __name__ == "__main__":
    main()
