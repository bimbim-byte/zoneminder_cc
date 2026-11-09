import ast
import sys

for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        ast.parse(f.read(), filename=path)
    print("SYNTAX OK:", path)
