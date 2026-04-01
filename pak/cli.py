"""Pak CLI - command-line interface for the Pak compiler."""

import sys
import os
import shutil
import argparse
import subprocess
import tomllib
from pathlib import Path
from typing import Optional, List

from .lexer import Lexer, LexError
from .parser import Parser, ParseError, parse
from .codegen import generate
from .typechecker import typecheck_multi, PakError
from .headergen import generate_header, module_to_filename, collect_module_includes
from . import ast as pak_ast


def find_project_root(start: Path = None) -> Optional[Path]:
    """Walk up directories to find pak.toml."""
    current = start or Path.cwd()
    while current != current.parent:
        if (current / 'pak.toml').exists():
            return current
        current = current.parent
    return None


def runtime_dir() -> Path:
    """Return the path to the bundled runtime/ directory."""
    return Path(__file__).parent.parent / 'runtime'


def parse_file(pak_file: Path, verbose: bool = False) -> Optional[pak_ast.Program]:
    """Parse a .pak file and return the AST, or None on error."""
    source = pak_file.read_text(encoding='utf-8')
    if verbose:
        print(f'  Parsing {pak_file.name}...')
    try:
        return parse(source, str(pak_file))
    except LexError as e:
        print(f'error[E001]: {e}', file=sys.stderr)
        print(f'  --> {pak_file}', file=sys.stderr)
        return None
    except ParseError as e:
        print(f'error[E002]: {e}', file=sys.stderr)
        print(f'  --> {pak_file}', file=sys.stderr)
        return None


def compile_file(pak_file: Path, verbose: bool = False,
                 module_headers: dict = None) -> tuple:
    """Parse and generate C for a .pak file. Returns (c_source, program) or exits."""
    program = parse_file(pak_file, verbose)
    if program is None:
        sys.exit(1)

    if verbose:
        print(f'  Generating C for {pak_file.name}...')
    c_source = generate(program, str(pak_file), module_headers=module_headers)
    return c_source, program


def _print_errors(errors: List[PakError], pak_file: Path, root: Path = None) -> int:
    """Print type errors and return the count."""
    for err in errors:
        print(str(err), file=sys.stderr)
    return len(errors)


def load_config(root: Path) -> dict:
    toml_path = root / 'pak.toml'
    with open(toml_path, 'rb') as f:
        return tomllib.load(f)


def _get_module_path(program: pak_ast.Program) -> Optional[str]:
    """Return the module path declared in a program, if any."""
    for decl in program.decls:
        if isinstance(decl, pak_ast.ModuleDecl):
            return decl.path
    return None


def cmd_build(args):
    """Compile .pak → C, pack assets, and generate Makefile."""
    root = find_project_root()
    if root is None:
        print('error: no pak.toml found. Run `pak init <name>` to create a project.', file=sys.stderr)
        sys.exit(1)

    config = load_config(root)
    project = config.get('project', {})
    project_name = project.get('name', 'game')
    rom_title = project.get('rom_title', project_name.upper()[:20])
    save_type = project.get('save_type', 'none')

    display = config.get('display', {})
    resolution = display.get('resolution', '320x240')
    bit_depth = display.get('bit_depth', 16)
    framebuffers = display.get('framebuffers', 3)

    deps = config.get('dependencies', {})
    use_tiny3d = bool(deps.get('tiny3d', False))

    build_cfg = config.get('build', {})
    optimization = build_cfg.get('optimization', 'debug')

    verbose = getattr(args, 'verbose', False)
    strict = getattr(args, 'strict', False)

    print(f'Building {project_name}...')

    build_dir = root / 'build'
    build_dir.mkdir(exist_ok=True)

    # ── 1. Parse all .pak files ───────────────────────────────────────────────
    src_files = sorted(f for f in root.glob('**/*.pak') if 'build' not in f.parts)
    if not src_files:
        print('error: no .pak source files found', file=sys.stderr)
        sys.exit(1)

    parsed: list = []  # [(pak_file, program)]
    for pak_file in src_files:
        program = parse_file(pak_file, verbose)
        if program is None:
            sys.exit(1)
        parsed.append((pak_file, program))

    # ── 2. Type-check all files together ──────────────────────────────────────
    tc_input = [(str(pak_file), prog) for pak_file, prog in parsed]
    all_errors = typecheck_multi(tc_input)
    total_errors = 0
    for filename, errors in all_errors.items():
        if errors:
            for err in errors:
                print(str(err), file=sys.stderr)
            total_errors += len(errors)
    if total_errors > 0:
        print(f'\n{total_errors} type error(s). Fix them before building.', file=sys.stderr)
        if strict:
            sys.exit(1)
        print('  (continuing build with --no-strict)', file=sys.stderr)

    # ── 3. Generate headers for modules ──────────────────────────────────────
    # Map: module_path → header_filename (e.g. 'game.player' → 'game_player.h')
    module_headers: dict = {}  # module_path → header filename
    for pak_file, program in parsed:
        mod_path = _get_module_path(program)
        if mod_path:
            header_name = module_to_filename(mod_path)
            # All headers go to build_dir root so -I$(BUILD_DIR) finds them all
            h_file = build_dir / header_name
            module_headers[mod_path] = header_name
            h_source = generate_header(program, mod_path)
            h_file.write_text(h_source, encoding='utf-8')
            if verbose:
                rel = pak_file.relative_to(root)
                print(f'  Header  {rel} -> {h_file.relative_to(root)}')

    # ── 4. Compile .pak → .c ─────────────────────────────────────────────────
    c_rel_paths = []
    for pak_file, program in parsed:
        rel = pak_file.relative_to(root)
        c_file = build_dir / rel.with_suffix('.c')
        c_file.parent.mkdir(parents=True, exist_ok=True)

        if verbose:
            print(f'  Generating C for {rel}...')
        c_source = generate(program, str(pak_file), module_headers=module_headers)
        c_file.write_text(c_source, encoding='utf-8')
        c_rel_paths.append(c_file.relative_to(root))
        print(f'  Compiled {rel} -> {c_file.relative_to(root)}')

    # ── 5. Copy runtime into project ──────────────────────────────────────────
    rt_src = runtime_dir()
    rt_dst = root / 'runtime'
    if rt_src.exists() and rt_src != rt_dst:
        rt_dst.mkdir(exist_ok=True)
        for f in rt_src.glob('*'):
            dst = rt_dst / f.name
            if not dst.exists():
                shutil.copy2(f, dst)
        print(f'  Runtime -> runtime/')

    # ── 6. Pack assets into PakFS archive ────────────────────────────────────
    asset_dirs = config.get('assets', {})
    packable = []
    for kind, rel_dir in asset_dirs.items():
        asset_path = root / rel_dir
        if asset_path.is_dir():
            for f in sorted(asset_path.rglob('*')):
                if f.is_file():
                    name = str(f.relative_to(root)).replace(os.sep, '/')
                    packable.append((name, f.read_bytes()))

    has_assets = bool(packable)
    pakfs_name = f'{project_name}.pakfs'
    if packable:
        from .pakfs import pack
        fs_dir = root / 'filesystem'
        fs_dir.mkdir(exist_ok=True)
        pakfs_file = fs_dir / pakfs_name
        pakfs_file.write_bytes(pack(packable))
        print(f'  Packed {len(packable)} asset(s) -> filesystem/{pakfs_name}')

    # ── 7. Generate Makefile ──────────────────────────────────────────────────
    from .makefile_gen import generate_makefile
    makefile = generate_makefile(
        project_name=project_name,
        rom_title=rom_title,
        c_files=c_rel_paths,
        pakfs_archive=pakfs_name if has_assets else None,
        save_type=save_type,
        bit_depth=bit_depth,
        resolution=resolution,
        framebuffers=framebuffers,
        optimization=optimization,
        use_tiny3d=use_tiny3d,
        project_root=root,
    )
    makefile_path = root / 'Makefile'
    makefile_path.write_text(makefile, encoding='utf-8')
    print(f'  Generated Makefile')

    print()
    print(f'Build complete. Next steps:')
    print(f'  1. Set N64_INST to your libdragon installation (export N64_INST=/opt/libdragon)')
    if use_tiny3d:
        print(f'  2. Set TINY3D_INST to your Tiny3D installation')
        print(f'  3. Run: make')
    else:
        print(f'  2. Run: make')
    print(f'  3. Run: make run   (launches in ares emulator)')


def cmd_check(args):
    """Type-check without building."""
    root = find_project_root()

    if root is None:
        # Single-file mode
        if getattr(args, 'files', None):
            tc_input = []
            for f in args.files:
                pak_file = Path(f)
                program = parse_file(pak_file)
                if program is not None:
                    tc_input.append((str(pak_file), program))

            if tc_input:
                all_errors = typecheck_multi(tc_input)
                total = 0
                for filename, errors in all_errors.items():
                    if errors:
                        for err in errors:
                            print(str(err), file=sys.stderr)
                        total += len(errors)
                    else:
                        print(f'{filename}: ok')
                if total:
                    sys.exit(1)
            return
        print('error: no pak.toml found', file=sys.stderr)
        sys.exit(1)

    src_files = sorted(f for f in root.glob('**/*.pak') if 'build' not in f.parts)
    tc_input = []
    parse_errors = 0
    for pak_file in src_files:
        program = parse_file(pak_file)
        if program is None:
            parse_errors += 1
        else:
            tc_input.append((str(pak_file), program))

    all_errors = typecheck_multi(tc_input)
    type_errors = 0
    for filename, errors in all_errors.items():
        rel = Path(filename).relative_to(root) if root else Path(filename)
        if errors:
            for err in errors:
                print(str(err), file=sys.stderr)
            type_errors += len(errors)
        else:
            print(f'  {rel}: ok')

    total = parse_errors + type_errors
    if total:
        print(f'\n{total} error(s) found.', file=sys.stderr)
        sys.exit(1)
    else:
        print(f'\nAll {len(src_files)} file(s) passed.')


def cmd_explain(args):
    """Show generated C for a .pak file."""
    pak_file = Path(args.file)
    if not pak_file.exists():
        print(f'error: file not found: {pak_file}', file=sys.stderr)
        sys.exit(1)
    c_source, _ = compile_file(pak_file)
    print(c_source)


def cmd_run(args):
    """Build, then invoke `make run`."""
    cmd_build(args)
    root = find_project_root()
    if root and (root / 'Makefile').exists():
        print('Running: make run')
        subprocess.run(['make', 'run'], cwd=root)


def cmd_pack(args):
    """Pack a directory of assets into a PakFS archive."""
    from .pakfs import pack_directory
    src = Path(args.source)
    out = Path(args.output)
    if not src.is_dir():
        print(f'error: {src} is not a directory', file=sys.stderr)
        sys.exit(1)
    count = pack_directory(src, out)
    print(f'Packed {count} file(s) into {out}')


def cmd_init(args):
    """Create a new project from template."""
    name = args.name
    project_dir = Path(name)
    if project_dir.exists():
        print(f'error: directory {name!r} already exists', file=sys.stderr)
        sys.exit(1)

    project_dir.mkdir()
    (project_dir / 'src').mkdir()
    (project_dir / 'assets').mkdir()
    (project_dir / 'assets' / 'sprites').mkdir()
    (project_dir / 'assets' / 'audio').mkdir()

    # ── pak.toml ──────────────────────────────────────────────────────────────
    (project_dir / 'pak.toml').write_text(f'''\
[project]
name = "{name}"
rom_title = "{name.upper()[:20]}"
save_type = "none"

[display]
resolution = "320x240"
bit_depth = 16
framebuffers = 3

[assets]
sprites = "assets/sprites/"
audio = "assets/audio/"

[dependencies]
tiny3d = false

[build]
optimization = "debug"
''', encoding='utf-8')

    # ── src/main.pak ──────────────────────────────────────────────────────────
    (project_dir / 'src' / 'main.pak').write_text(f'''\
-- {name}
-- Created with: pak init {name}

use n64.display
use n64.controller
use n64.rdpq

entry {{
    -- Initialize display: 320x240, 16bpp, triple-buffered
    display.init(RESOLUTION_320x240, DEPTH_16_BPP, 3, GAMMA_NONE, FILTERS_RESAMPLE)

    loop {{
        let input = controller.read(0)

        -- Begin frame
        let disp = display.get()
        rdpq.attach_clear(disp, none)

        -- ── Game logic here ─────────────────────────────────────────────

        rdpq.detach_show()
    }}
}}
''', encoding='utf-8')

    # ── Copy runtime ──────────────────────────────────────────────────────────
    rt_src = runtime_dir()
    if rt_src.exists():
        rt_dst = project_dir / 'runtime'
        shutil.copytree(rt_src, rt_dst)

    # ── .gitignore ────────────────────────────────────────────────────────────
    (project_dir / '.gitignore').write_text('''\
build/
filesystem/
Makefile
*.z64
*.elf
''', encoding='utf-8')

    print(f"Created project '{name}'")
    print(f'  {name}/pak.toml')
    print(f'  {name}/src/main.pak')
    print(f'  {name}/runtime/       (PakFS C runtime)')
    print()
    print('Next steps:')
    print(f'  cd {name}')
    print(f'  export N64_INST=/opt/libdragon   # or wherever libdragon is installed')
    print(f'  pak build && make')


def cmd_clean(args):
    """Remove build artifacts."""
    root = find_project_root()
    if root is None:
        print('error: no pak.toml found', file=sys.stderr)
        sys.exit(1)
    removed = []
    for target in ['build', 'filesystem']:
        d = root / target
        if d.exists():
            shutil.rmtree(d)
            removed.append(str(d.relative_to(root)))
    for target in ['Makefile']:
        f = root / target
        if f.exists():
            f.unlink()
            removed.append(target)
    # Remove generated .z64 / .elf
    for pat in ['*.z64', '*.elf']:
        for f in root.glob(pat):
            f.unlink()
            removed.append(f.name)
    if removed:
        print('Cleaned: ' + ', '.join(removed))
    else:
        print('Nothing to clean.')


def cmd_runtime_dir(args):
    """Print the path to the bundled runtime (used by generated Makefile)."""
    print(runtime_dir())


def main():
    parser = argparse.ArgumentParser(
        prog='pak',
        description='Pak - A language for Nintendo 64 homebrew development',
    )
    parser.add_argument('--version', action='version', version='pak 0.1.0')

    sub = parser.add_subparsers(dest='command', metavar='COMMAND')

    # build
    p_build = sub.add_parser('build', help='Compile .pak to C, pack assets, generate Makefile')
    p_build.add_argument('-v', '--verbose', action='store_true')
    p_build.add_argument('--strict', action='store_true',
                         help='Fail on type errors (default: warn and continue)')
    p_build.set_defaults(func=cmd_build)

    # check
    p_check = sub.add_parser('check', help='Type-check without building')
    p_check.add_argument('files', nargs='*')
    p_check.set_defaults(func=cmd_check)

    # explain
    p_explain = sub.add_parser('explain', help='Show generated C for a .pak file')
    p_explain.add_argument('file', help='.pak file')
    p_explain.set_defaults(func=cmd_explain)

    # run
    p_run = sub.add_parser('run', help='Build then `make run` (launches in ares)')
    p_run.add_argument('-v', '--verbose', action='store_true')
    p_run.add_argument('--strict', action='store_true')
    p_run.set_defaults(func=cmd_run)

    # init
    p_init = sub.add_parser('init', help='Create a new project')
    p_init.add_argument('name', help='Project name')
    p_init.set_defaults(func=cmd_init)

    # clean
    p_clean = sub.add_parser('clean', help='Remove build artifacts and generated Makefile')
    p_clean.set_defaults(func=cmd_clean)

    # pack
    p_pack = sub.add_parser('pack', help='Pack an asset directory into a PakFS archive')
    p_pack.add_argument('source', help='Source directory')
    p_pack.add_argument('--output', '-o', required=True, help='Output .pakfs file')
    p_pack.set_defaults(func=cmd_pack)

    # runtime-dir (internal, used by generated Makefile)
    p_rtdir = sub.add_parser('--runtime-dir', help=argparse.SUPPRESS)
    p_rtdir.set_defaults(func=cmd_runtime_dir)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(0)
    args.func(args)


if __name__ == '__main__':
    main()
