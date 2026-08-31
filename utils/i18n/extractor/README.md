# Resistine i18n Extractor

A small development tool for collecting existing localization files from Resistine projects into one directory that can later be reviewed and connected to Weblate.

The script does **not** run Git commands, create commits, push changes, or connect to GitHub.

## Current scope

The extractor collects localization resources that already exist in the source projects.

Currently tested with:

- Android: `strings.xml`
- Resistine Desktop: JSON localization files such as `utils/i18n/en.json`

The script can also support other configured formats, including:

- Apple: `.strings`, `.stringsdict`, `.xcstrings`
- Windows: `.resx`
- Linux: `.po`, `.pot`, Qt `.ts`
- Generic localization files: `.json`

> The current version does not scan source code for hardcoded user-facing text such as `Text("Sign in")` or `button.setText("Save")`.

## Requirements

- Python 3.11 or newer
- Local copies of the Resistine source projects
- No additional Python packages are required

Check your Python version:

```bash
python --version
```

## Files to share with testers

Only these files are required:

```text
extract.py
i18n-extract.toml
README.md
```

Do not include generated directories such as `locales/` or `build/` in the initial test package.

## Recommended directory structure

```text
resistine-i18n-test/
├── extract.py
├── i18n-extract.toml
├── README.md
└── projects/
    ├── Resistine-Android-feel/
    └── Resistine-Desktop-develop/
```

The projects may also be stored elsewhere. In that case, use absolute paths in the TOML configuration.

## Configuration

Example `i18n-extract.toml` for Android and Resistine Desktop:

```toml
[project]
output_dir = "locales"
report_path = "build/i18n-extract-report.json"
state_path = "build/i18n-extract-state.json"

[[sources]]
name = "android"
platform = "android"
path = "projects/Resistine-Android-feel/app/src/main/res"
destination = "android"

include = [
  "**/values*/strings*.xml"
]

exclude = [
  "**/build/**"
]

[[sources]]
name = "desktop"
platform = "generic"
path = "projects/Resistine-Desktop-develop/utils/i18n"
destination = "desktop"

include = [
  "**/*.json"
]

exclude = []
```

Paths are resolved relative to the directory containing `i18n-extract.toml`.

### Absolute path example on Linux

```toml
path = "/home/username/projects/Resistine-Android-feel/app/src/main/res"
```

### Absolute path example on Windows

Use forward slashes:

```toml
path = "C:/Projects/Resistine-Android-feel/app/src/main/res"
```

## Usage

Run all commands from the directory containing `extract.py` and `i18n-extract.toml`.

### Show available options

```bash
python extract.py --help
```

### Preview changes without writing files

```bash
python extract.py \
  --config i18n-extract.toml \
  --dry-run \
  --verbose
```

Expected output for the current Resistine projects is similar to:

```text
INFO: android: found 1 localization file(s)
INFO: desktop: found 1 localization file(s)
INFO: Planned: 2 file(s), 2 create, 0 update, 0 unchanged, 0 removed, 645 string(s), 0 invalid
INFO: Git operations: disabled
```

### Run the extraction

```bash
python extract.py \
  --config i18n-extract.toml \
  --strict
```

### Process only Android

```bash
python extract.py \
  --config i18n-extract.toml \
  --source android \
  --dry-run \
  --verbose
```

### Process only Desktop

```bash
python extract.py \
  --config i18n-extract.toml \
  --source desktop \
  --dry-run \
  --verbose
```

### Check whether generated files are up to date

```bash
python extract.py --config i18n-extract.toml --check
echo $?
```

Exit codes:

- `0` — generated files are up to date
- `2` — source files changed and extraction is required
- `1` — an error occurred

## Generated files

After a successful run, the output should look similar to:

```text
locales/
├── android/
│   └── values/
│       └── strings.xml
└── desktop/
    └── en.json

build/
├── i18n-extract-report.json
└── i18n-extract-state.json
```

The extractor copies files into the output directory. It does not modify the original project files.

## Verify the result

### Count Desktop strings

```bash
python - <<'PY'
import json

with open("locales/desktop/en.json", encoding="utf-8") as file:
    data = json.load(file)

print("Desktop:", len(data), "strings")
PY
```

### Count Android string resources

```bash
python - <<'PY'
import xml.etree.ElementTree as ET

root = ET.parse("locales/android/values/strings.xml").getroot()
print("Android:", len(root.findall("string")), "strings")
PY
```

For the currently tested project versions, the expected result is approximately:

```text
Desktop: 49 strings
Android: 596 strings
Total: 645 strings
```

Counts may change as the projects evolve.

## View the report

```bash
python -m json.tool build/i18n-extract-report.json | less
```

Press `q` to exit `less`.

## Important limitations

The extractor currently collects only strings that are already stored in localization resources.

It does not detect hardcoded text in source code, for example:

```kotlin
Text("Create account")
```

```python
button.setText("Save")
```

A separate source-code scanner will be needed to identify those strings and report their file names and line numbers.

## Third-party frameworks

Do not collect localization resources bundled inside third-party frameworks unless they are intentionally maintained by the Resistine team.

For example, exclude bundled Sparkle framework translations:

```text
frameworks/Sparkle.framework/
```

These strings belong to the external framework and should not be sent to the Resistine Weblate project.

## Troubleshooting

### `Source path does not exist`

Check the `path` value in `i18n-extract.toml` and make sure the project has been extracted or cloned locally.

### `found 0 localization file(s)`

Check:

- whether the path points to the correct directory,
- whether the `include` pattern matches the files,
- whether the project stores translations in a different format.

### UTF-8 decoding errors in a third-party framework

Narrow the source path or add an exclusion for the framework. For Resistine Desktop, point the generic JSON source directly to:

```text
Resistine-Desktop-develop/utils/i18n
```

rather than scanning the entire repository.

## Git policy

This tool never performs:

```text
git add
git commit
git push
```

Reviewing changes and publishing them to GitHub must be done manually or by a separate CI process.
