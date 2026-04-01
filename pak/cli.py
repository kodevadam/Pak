"""Pak CLI - command-line interface for the Pak compiler."""

import sys
import os
import argparse
import subprocess
import tomllib
from pathlib import Path
from typing import Optional

from .lexer import Lexer, LexError
from .parser import Parser, ParseError, parse
from .codegen import generate
from . import ast as pak_ast


def find_project_root(start: Path = None) -> Optional[Path]:
    """Walk up directories to find pak.toml."""
    current = start or Path.cwd()
    while current != current.parent:
        if (current / 'pak.toml').exists():
            return current
        current = current.parent
    return None


def compile_file(pak_file: Path, verbose: bool = False) -> tuple:
    """Compile a .pak file, return (c_source, program)."""
    source = pak_file.read_text(encoding='utf-8')
    if verbose:
        print(f'  Lexing {pak_file.name}...')
    try:
        program = parse(source, str(pak_file))
    except LexError as e:
        print(f'error[E001]: {e}', file=sys.stderr)
        print(f'  --> {pak_file}', file=sys.stderr)
        sys.exit(1)
    except ParseError as e:
        print(f'error[E002]: {e}', file=sys.stderr)
        print(f'  --> {pak_file}', file=sys.stderr)
        sys.exit(1)

    if verbose:
        print(f'  Generating C for {pak_file.name}...')
    c_source = generate(program, str(pak_file))
    return c_source, program


def cmd_build(args):
    """Build the project into a .z64 ROM."""
    root = find_project_root()
    if root is None:
        print('error: no pak.toml found. Run `pak init <name>` to create a project.', file=sys.stderr)
        sys.exit(1)

    toml_path = root / 'pak.toml'
    with open(toml_path, 'rb') as f:
        config = tomllib.load(f)

    project_name = config.get('project', {}).get('name', 'game')
    print(f'Building {project_name}...')

    build_dir = root / 'build'
    build_dir.mkdir(exist_ok=True)

    # Find all .pak files
    src_files = list(root.glob('**/*.pak'))
    if not src_files:
        print('error: no .pak source files found', file=sys.stderr)
        sys.exit(1)

    c_files = []
    for pak_file in src_files:
        rel = pak_file.relative_to(root)
        c_file = build_dir / rel.with_suffix('.c')
        c_file.parent.mkdir(parents=True, exist_ok=True)

        c_source, _ = compile_file(pak_file, verbose=args.verbose)
        c_file.write_text(c_source, encoding='utf-8')
        c_files.append(c_file)
        print(f'  Compiled {rel} -> {c_file.relative_to(root)}')

    # Pack assets into PakFS archive
    asset_dirs = config.get('assets', {})
    packable = []
    for kind, rel_dir in asset_dirs.items():
        asset_path = root / rel_dir
        if asset_path.is_dir():
            for f in sorted(asset_path.rglob('*')):
                if f.is_file():
                    name = str(f.relative_to(root)).replace(os.sep, '/')
                    packable.append((name, f.read_bytes()))

    if packable:
        from .pakfs import pack
        pakfs_file = build_dir / f'{project_name}.pakfs'
        pakfs_file.write_bytes(pack(packable))
        print(f'  Packed {len(packable)} asset(s) -> {pakfs_file.relative_to(root)}')

    print(f'Build complete. Generated {len(c_files)} C file(s) in {build_dir.relative_to(root)}/')
    print()
    print('Note: To produce a .z64 ROM, run the generated C files through')
    print('      a libdragon Makefile in your N64 development environment.')
    print('      Assets are packed into a PakFS archive (pak:/ protocol).')


def cmd_check(args):
    """Type-check without building."""
    root = find_project_root()
    if root is None:
        # Try current file if given
        if args.files:
            for f in args.files:
                pak_file = Path(f)
                try:
                    compile_file(pak_file)
                    print(f'{f}: ok')
                except SystemExit:
                    pass
            return
        print('error: no pak.toml found', file=sys.stderr)
        sys.exit(1)

    src_files = list(root.glob('**/*.pak'))
    errors = 0
    for pak_file in src_files:
        try:
            compile_file(pak_file)
            print(f'  {pak_file.relative_to(root)}: ok')
        except SystemExit:
            errors += 1

    if errors:
        print(f'\n{errors} error(s) found.')
        sys.exit(1)
    else:
        print(f'\nAll {len(src_files)} file(s) passed.')


def cmd_explain(args):
    """Show generated C with hardware comments."""
    pak_file = Path(args.file)
    if not pak_file.exists():
        print(f'error: file not found: {pak_file}', file=sys.stderr)
        sys.exit(1)

    c_source, _ = compile_file(pak_file)
    print(c_source)


def cmd_run(args):
    """Build and launch in emulator."""
    cmd_build(args)
    # Try to find ares emulator
    ares = 'ares'
    root = find_project_root()
    if root:
        toml_path = root / 'pak.toml'
        with open(toml_path, 'rb') as f:
            config = tomllib.load(f)
        project_name = config.get('project', {}).get('name', 'game')
        rom = root / 'build' / f'{project_name}.z64'
        if rom.exists():
            print(f'Launching {rom.name} in emulator...')
            subprocess.run([ares, str(rom)])
        else:
            print(f'Note: ROM not yet produced ({project_name}.z64).')
            print('      Run through libdragon Makefile to produce the ROM, then launch with ares.')


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

    # pak.toml
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

    # main.pak
    (project_dir / 'src' / 'main.pak').write_text(f'''\
-- {name} - created with pak init

use n64.display
use n64.controller
use n64.rdpq

entry {{
    -- Initialize display
    display.init(RESOLUTION_320x240, DEPTH_16_BPP, 3, GAMMA_NONE, FILTERS_RESAMPLE)

    loop {{
        -- Read controller input
        let input = controller.read(0)

        -- Begin frame
        let disp = display.get()
        rdpq.attach_clear(disp, none)

        -- Your game logic here

        rdpq.detach_show()
    }}
}}
''', encoding='utf-8')

    print(f'Created project {name!r}')
    print(f'  {name}/pak.toml')
    print(f'  {name}/src/main.pak')
    print()
    print(f'Next steps:')
    print(f'  cd {name}')
    print(f'  pak build')


def cmd_clean(args):
    """Remove build artifacts."""
    root = find_project_root()
    if root is None:
        print('error: no pak.toml found', file=sys.stderr)
        sys.exit(1)
    import shutil
    build_dir = root / 'build'
    if build_dir.exists():
        shutil.rmtree(build_dir)
        print('Cleaned build directory.')
    else:
        print('Nothing to clean.')


def main():
    parser = argparse.ArgumentParser(
        prog='pak',
        description='Pak - A language for Nintendo 64 homebrew development',
    )
    parser.add_argument('--version', action='version', version='pak 0.1.0')

    sub = parser.add_subparsers(dest='command', metavar='COMMAND')

    # build
    p_build = sub.add_parser('build', help='Compile to C (and .z64 ROM with libdragon)')
    p_build.add_argument('-v', '--verbose', action='store_true')
    p_build.set_defaults(func=cmd_build)

    # check
    p_check = sub.add_parser('check', help='Type-check without building')
    p_check.add_argument('files', nargs='*')
    p_check.set_defaults(func=cmd_check)

    # explain
    p_explain = sub.add_parser('explain', help='Show generated C with hardware comments')
    p_explain.add_argument('file', help='.pak file to explain')
    p_explain.set_defaults(func=cmd_explain)

    # run
    p_run = sub.add_parser('run', help='Build and launch in Ares emulator')
    p_run.add_argument('-v', '--verbose', action='store_true')
    p_run.set_defaults(func=cmd_run)

    # init
    p_init = sub.add_parser('init', help='Create a new project')
    p_init.add_argument('name', help='Project name')
    p_init.set_defaults(func=cmd_init)

    # clean
    p_clean = sub.add_parser('clean', help='Remove build artifacts')
    p_clean.set_defaults(func=cmd_clean)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(0)
    args.func(args)


if __name__ == '__main__':
    main()
