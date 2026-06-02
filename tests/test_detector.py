"""Tests for the file detector module."""



from graphfocus.detect.detector import FileType, classify_file, detect_files


class TestClassifyFile:
    def test_python_file(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("print('hello')")
        assert classify_file(f) == FileType.CODE

    def test_java_file(self, tmp_path):
        f = tmp_path / "Test.java"
        f.write_text("public class Test {}")
        assert classify_file(f) == FileType.CODE

    def test_sql_file(self, tmp_path):
        f = tmp_path / "schema.sql"
        f.write_text("CREATE TABLE test (id INT);")
        assert classify_file(f) == FileType.CODE

    def test_plsql_file(self, tmp_path):
        f = tmp_path / "pkg.pks"
        f.write_text("CREATE PACKAGE pkg AS END;")
        assert classify_file(f) == FileType.CODE

    def test_csharp_file(self, tmp_path):
        f = tmp_path / "Test.cs"
        f.write_text("class Test {}")
        assert classify_file(f) == FileType.CODE

    def test_markdown_file(self, tmp_path):
        f = tmp_path / "readme.md"
        f.write_text("# Hello World")
        assert classify_file(f) == FileType.DOCUMENT

    def test_image_file(self, tmp_path):
        f = tmp_path / "logo.png"
        f.write_bytes(b"\x89PNG")
        assert classify_file(f) == FileType.IMAGE

    def test_unknown_extension(self, tmp_path):
        f = tmp_path / "data.xyz"
        f.write_text("unknown")
        assert classify_file(f) is None


class TestDetectFiles:
    def test_detect_mixed_project(self, tmp_path):
        (tmp_path / "app.py").write_text("import os")
        (tmp_path / "Service.java").write_text("class Service {}")
        (tmp_path / "schema.sql").write_text("CREATE TABLE t (id INT);")
        (tmp_path / "readme.md").write_text("# README")

        result = detect_files(tmp_path)

        assert result["total_files"] == 4
        assert result["by_type"]["code"] == 3
        assert result["by_type"]["document"] == 1
        assert result["by_language"]["python"] == 1
        assert result["by_language"]["java"] == 1

    def test_skip_sensitive_files(self, tmp_path):
        (tmp_path / "app.py").write_text("import os")
        (tmp_path / ".env").write_text("SECRET=123")
        (tmp_path / "private.key").write_text("key data")

        result = detect_files(tmp_path)

        assert result["total_files"] == 1
        assert result["skipped_sensitive"] == 2

    def test_skip_excluded_dirs(self, tmp_path):
        (tmp_path / "app.py").write_text("code")
        node_modules = tmp_path / "node_modules"
        node_modules.mkdir()
        (node_modules / "lib.js").write_text("js code")

        result = detect_files(tmp_path)

        assert result["total_files"] == 1

    def test_empty_directory(self, tmp_path):
        result = detect_files(tmp_path)
        assert result["total_files"] == 0

    def test_include_glob(self, tmp_path):
        (tmp_path / "app.py").write_text("import os")
        (tmp_path / "ignore.py").write_text("import os")
        (tmp_path / "schema.sql").write_text("CREATE TABLE t (id INT);")
        result = detect_files(tmp_path, include=["*.sql"])
        paths = [f["relative_path"] for f in result["files"]]
        assert paths == ["schema.sql"]

    def test_exclude_glob(self, tmp_path):
        (tmp_path / "app.py").write_text("x = 1")
        (tmp_path / "test_app.py").write_text("x = 1")
        result = detect_files(tmp_path, exclude=["test_*.py"])
        paths = sorted(f["relative_path"] for f in result["files"])
        assert paths == ["app.py"]

    def test_include_takes_precedence_over_default_languages(self, tmp_path):
        (tmp_path / "app.py").write_text("x = 1")
        (tmp_path / "schema.sql").write_text("CREATE TABLE t (id INT);")
        (tmp_path / "Service.java").write_text("class Service{}")
        result = detect_files(tmp_path, include=["*.java", "*.py"])
        langs = sorted({f["language"] for f in result["files"]})
        assert langs == ["java", "python"]
