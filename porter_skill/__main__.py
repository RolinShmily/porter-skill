"""Main module entrypoint when invoked as `python -m porter_skill`."""

import sys

from porter_skill.cli import main

if __name__ == "__main__":
    sys.exit(main())
