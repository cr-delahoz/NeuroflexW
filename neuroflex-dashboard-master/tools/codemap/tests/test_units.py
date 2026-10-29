import unittest

import _util  # noqa: F401  (añade el paquete al path)

from codemap_core import diffparse, sections, symbols, tags

SAMPLE_DIFF = """\
diff --git a/app/views.py b/app/views.py
index 111..222 100644
--- a/app/views.py
+++ b/app/views.py
@@ -1,3 +1,4 @@
 import os
+import requests

 def a():
diff --git a/new file.txt b/new file.txt
new file mode 100644
--- /dev/null
+++ b/new file.txt
@@ -0,0 +1,2 @@
+hola
+-- no es un encabezado
diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1 +0,0 @@
-x = 1
\\ No newline at end of file
diff --git a/a/x.py b/b/y.py
similarity index 100%
rename from a/x.py
rename to b/y.py
diff --git a/logo.png b/logo.png
Binary files a/logo.png and b/logo.png differ
"""


class DiffParseTests(unittest.TestCase):
    def setUp(self):
        self.files = {f.path: f for f in diffparse.parse(SAMPLE_DIFF)}

    def test_statuses_and_paths(self):
        self.assertEqual(self.files["app/views.py"].status, "modified")
        self.assertEqual(self.files["new file.txt"].status, "added")
        self.assertEqual(self.files["old.py"].status, "deleted")
        renamed = self.files["b/y.py"]
        self.assertEqual((renamed.status, renamed.old_path, renamed.similarity), ("renamed", "a/x.py", 100))
        self.assertTrue(self.files["logo.png"].binary)

    def test_line_numbers(self):
        lines = self.files["app/views.py"].hunks[0].lines
        added = [ln for ln in lines if ln.kind == "+"]
        self.assertEqual([(ln.new_no, ln.text) for ln in added], [(2, "import requests")])

    def test_content_that_looks_like_a_header(self):
        new_file = self.files["new file.txt"]
        self.assertEqual([ln.text for ln in new_file.hunks[0].lines], ["hola", "-- no es un encabezado"])
        self.assertEqual(new_file.added, 2)

    def test_unquote(self):
        self.assertEqual(diffparse.unquote('"caf\\303\\251 \\"x\\".py"'), 'café "x".py')


class SymbolTests(unittest.TestCase):
    def test_python_symbols_include_decorators_and_methods(self):
        text = "import os\n\n@login_required\ndef view(request):\n    return 1\n\nclass A:\n    def m(self):\n        pass\n"
        syms = {s.name: s for s in symbols.extract("v.py", text)}
        self.assertEqual((syms["view"].start, syms["view"].end, syms["view"].kind), (3, 5, "función"))
        self.assertEqual(syms["view"].decorators, ["login_required"])
        self.assertEqual(syms["A.m"].kind, "método")
        self.assertEqual(symbols.innermost(list(syms.values()), 9).name, "A.m")
        self.assertIsNone(symbols.innermost(list(syms.values()), 1))

    def test_python_syntax_error(self):
        with self.assertRaises(symbols.ParseFailure):
            symbols.extract("v.py", "def broken(:\n")

    def test_django_blocks(self):
        text = "{% extends 'base.html' %}\n{% block content %}\n<p>x</p>\n{% block inner %}y{% endblock %}\n{% endblock %}\n"
        syms = {s.name: (s.start, s.end) for s in symbols.extract("t.html", text)}
        self.assertEqual(syms, {"inner": (4, 4), "content": (2, 5)})

    def test_javascript_functions(self):
        text = "function a() {\n  if (x) { y(); }\n}\nconst b = async (z) => {\n  return z;\n};\n"
        syms = {s.name: (s.start, s.end) for s in symbols.extract("app.js", text)}
        self.assertEqual(syms, {"a": (1, 3), "b": (4, 6)})

    def test_markdown_headings_skip_code_fences(self):
        text = "# Uno\ntexto\n```\n# no\n```\n## Dos\n"
        self.assertEqual([(s.name, s.start, s.end) for s in symbols.extract("r.md", text)],
                         [("Uno", 1, 5), ("Dos", 6, 6)])

    def test_unsupported_extension(self):
        self.assertIsNone(symbols.extract("data.json", "{}"))


class SectionTests(unittest.TestCase):
    def test_globs(self):
        self.assertTrue(sections.glob_to_regex("**/views.py").match("views.py"))
        self.assertTrue(sections.glob_to_regex("**/views.py").match("a/b/views.py"))
        self.assertFalse(sections.glob_to_regex("*.py").match("a/b.py"))
        self.assertTrue(sections.glob_to_regex("ml/**").match("ml/models/x.pkl"))

    def test_first_matching_rule_wins(self):
        matcher = sections.SectionMatcher({"secciones": [
            {"nombre": "Tests", "rutas": ["**/tests/**"]},
            {"nombre": "Backend", "rutas": ["**/views.py"]},
            {"nombre": "Red", "contenido": [r"import requests"]},
        ], "excluir": ["build/**"]})
        self.assertEqual(matcher.section_for("app/tests/views.py"), "Tests")
        self.assertEqual(matcher.section_for("app/views.py"), "Backend")
        self.assertEqual(matcher.section_for("x.py", "import requests\n"), "Red")
        self.assertEqual(matcher.section_for("x.py", ""), sections.UNCLASSIFIED)
        self.assertTrue(matcher.excluded("build/out.txt"))


class TagTests(unittest.TestCase):
    def names(self, path, added, removed=()):
        return {t.nombre for t in tags.detect(path, list(added), list(removed))}

    def test_effects_on_added_lines(self):
        self.assertEqual(self.names("a.py", ["    requests.post(url, json=data)"]), {"red"})
        self.assertIn("borrado", self.names("a.py", ["    shutil.rmtree(path)"]))
        self.assertIn("secretos", self.names("a.py", ['API_KEY = "abc123"']))

    def test_comments_and_prose_are_ignored(self):
        self.assertEqual(self.names("a.py", ["# requests.get(x) en el futuro"]), set())
        self.assertEqual(self.names("notes.md", ["usa requests.get(x)"]), set())

    def test_removed_permission_check(self):
        self.assertEqual(self.names("v.py", [], ["@login_required"]), {"quita permisos"})
        self.assertEqual(self.names("v.py", ["@role_required('ADMIN')"], ["@login_required"]), {"permisos"})

    def test_moved_lines_do_not_count(self):
        added, removed = ["        @login_required"], ["@login_required"]
        ignore = tags.moved_lines(added, removed)
        self.assertEqual({t.nombre for t in tags.detect("v.py", [], removed, ignore)}, set())

    def test_tailwind_truncate_is_not_a_deletion(self):
        self.assertEqual(self.names("t.html", ['<p class="truncate">x</p>']), set())

    def test_dependency_files(self):
        self.assertEqual(self.names("requirements.txt", ["httpx==0.27"]), {"dependencias"})


if __name__ == "__main__":
    unittest.main()
