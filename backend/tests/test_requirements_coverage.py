import ast
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
REQUIREMENTS = ROOT / "requirements.txt"
SCAN_ROOTS = (ROOT / "backend", ROOT / "scripts")

IMPORT_TO_PACKAGE = {
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "google": "google-genai",
    "keycloak": "python-keycloak",
    "openai": "openai",
    "playwright": "playwright",
    "psycopg2": "psycopg2-binary",
    "pydantic": "pydantic",
    "pypdf": "pypdf",
    "qdrant_client": "qdrant-client",
    "requests": "requests",
    "tenacity": "tenacity",
}


def declared_packages() -> set[str]:
    packages = set()
    for raw_line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        name = line.split(";", 1)[0].split("==", 1)[0].strip()
        packages.add(name.lower())
    return packages


def imported_top_level_modules() -> set[str]:
    modules = set()
    for scan_root in SCAN_ROOTS:
        for path in scan_root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules.update(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    modules.add(node.module.split(".", 1)[0])
    return modules


class RequirementsCoverageTests(unittest.TestCase):
    def test_every_external_import_has_a_declared_distribution(self):
        imported = imported_top_level_modules() - set(sys.stdlib_module_names) - {"backend"}
        unknown = sorted(imported - set(IMPORT_TO_PACKAGE))
        self.assertEqual(unknown, [], f"Add package mappings for external imports: {unknown}")

        declared = declared_packages()
        missing = sorted(
            IMPORT_TO_PACKAGE[module]
            for module in imported
            if IMPORT_TO_PACKAGE[module].lower() not in declared
        )
        self.assertEqual(missing, [], f"Missing direct requirements: {missing}")

    def test_xml_parser_dependency_is_explicit(self):
        self.assertIn("lxml", declared_packages())


if __name__ == "__main__":
    unittest.main()
