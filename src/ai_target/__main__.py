"""
Package entrypoint for `python -m ai_target`.
"""

import sys
from ai_target.cli import main

if __name__ == "__main__":
    sys.exit(main())
