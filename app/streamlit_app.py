from pathlib import Path

app_path = Path(__file__).with_name("app.py")
code = app_path.read_text(encoding="utf-8")
exec(compile(code, str(app_path), "exec"))
