"""Export bounded local diagnostics; no environment loading, network or secret discovery."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from mira.adapters.diagnostics.export import export_diagnostics  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT / "var" / "diagnostics")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-reviewed-raw", action="store_true",
                        help="Include privacy-reviewed dialogue/model/audio; sensitive, local only.")
    parser.add_argument("--confirm-sensitive-export", action="store_true",
                        help="Separate consent to package raw content. Review before sharing.")
    args = parser.parse_args(argv)
    try:
        manifest = export_diagnostics(args.root, args.output,
            include_raw=args.include_reviewed_raw,
            confirm_sensitive_export=args.confirm_sensitive_export)
    except (OSError, ValueError):
        print("Diagnostic export failed: check destination, local permissions and raw-export consent.",
              file=sys.stderr)
        return 2
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
