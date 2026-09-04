#!/usr/bin/env python3
"""
Validation script for translation files.
Checks that German and English translations have identical structure.
"""

import json
import sys
import re
from pathlib import Path

# Relative to this file, not to an absolute path on one developer's laptop.
FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"


def collect_keys(d, prefix=""):
    """Recursively collect all JSON keys as dot-notation paths."""
    result = set()
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            result.update(collect_keys(v, full_key))
        else:
            result.add(full_key)
    return result


def validate_translation_files():
    """Validate that translation files exist and have matching structure."""
    de_file = FRONTEND_DIR / "src" / "translations" / "de.json"
    en_file = FRONTEND_DIR / "src" / "translations" / "en.json"
    test_file = FRONTEND_DIR / "src" / "translations" / "translations.test.js"
    
    errors = []
    
    # Check files exist
    if not de_file.exists():
        errors.append(f"✗German translation file missing: {de_file}")
    else:
        print(f"✓German translation file exists: {de_file}")
    
    if not en_file.exists():
        errors.append(f"✗English translation file missing: {en_file}")
    else:
        print(f"✓English translation file exists: {en_file}")
    
    if not test_file.exists():
        errors.append(f"✗Translation test file missing: {test_file}")
    else:
        print(f"✓Translation test file exists: {test_file}")
    
    if errors:
        return False
    
    # Load and parse files
    try:
        with open(de_file) as f:
            de = json.load(f)
    except json.JSONDecodeError as e:
        errors.append(f"✗German translation file is invalid JSON: {e}")
        return False
    
    try:
        with open(en_file) as f:
            en = json.load(f)
    except json.JSONDecodeError as e:
        errors.append(f"✗English translation file is invalid JSON: {e}")
        return False
    
    # Check structure matches
    de_keys = collect_keys(de)
    en_keys = collect_keys(en)
    
    if de_keys != en_keys:
        errors.append("✗Translation files have different structure")
        if de_keys - en_keys:
            errors.append(f"  DE only keys: {de_keys - en_keys}")
        if en_keys - de_keys:
            errors.append(f"  EN only keys: {en_keys - de_keys}")
        return False
    else:
        print(f"✓Translation files have identical structure ({len(de_keys)} keys)")
    
    # Check that German strings are different from English (except for loanwords)
    def get_nested(d, path):
        keys = path.split('.')
        val = d
        for k in keys:
            val = val[k]
        return val
    
    # Common English loanwords that are acceptable in German
    acceptable_loanwords = {
        'tags.vegan', 'tags.strohschwein', 'tags.leinetalerrind',  # Brand/product names
        'mealTypes.dessert',  # Dessert is used in German
        # These three are the German word too. They only surface now because
        # FRONTEND_DIR used to point at a directory that does not exist on this
        # host, so this script exited at the "file missing" check and never
        # reached the comparison.
        'ui.upvote', 'ui.downvote',
        'ui.theme_system',
    }
    
    differences_found = False
    for key in de_keys:
        de_val = get_nested(de, key)
        en_val = get_nested(en, key)
        if de_val == en_val and key not in acceptable_loanwords:
            errors.append(f"✗Same string in both languages: {key} = '{de_val}'")
        else:
            differences_found = True
    
    if differences_found:
        print("✓German and English translations differ")
    
    # Check for interpolation placeholders (i18next uses {{var}} not {var})
    combined = json.dumps(de) + json.dumps(en)
    single_brace_placeholders = [m for m in 
        re.findall(r'(?<!\{)\{[a-zA-Z]\w*\}(?!\})', combined)]
    if single_brace_placeholders:
        errors.append(f"✗Found single-brace interpolation placeholders: {single_brace_placeholders}")
    else:
        print("✓No single-brace interpolation placeholders found")
    
    if errors:
        print("\nErrors found:")
        for err in errors:
            print(err)
        return False
    
    return True


def main():
    print("=" * 60)
    print("TRANSLATION FILES VALIDATION")
    print("=" * 60)
    print()
    
    if validate_translation_files():
        print()
        print("=" * 60)
        print("ALL TRANSLATION VALIDATIONS PASSED")
        print("=" * 60)
        return 0
    else:
        print()
        print("=" * 60)
        print("TRANSLATION VALIDATION FAILED")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())