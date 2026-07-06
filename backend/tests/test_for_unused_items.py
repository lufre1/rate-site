#!/usr/bin/env python3
"""
Comprehensive test script to check if items are actually in use.
Run with: python tests/test_for_unused_items.py
"""

import json
import os
import re
import sys
from pathlib import Path

# Setup paths
SCRIPT_DIR = Path(__file__).parent
BACKEND_DIR = SCRIPT_DIR.parent
# Try multiple possible frontend locations
FRONTEND_DIR = None
possible_paths = [
    SCRIPT_DIR.parent.parent / "frontend",
    Path("/frontend"),
    Path("/home/freckmann15/Documents/rate-site/frontend"),
]
for path in possible_paths:
    if path.exists():
        FRONTEND_DIR = path
        break
if not FRONTEND_DIR:
    FRONTEND_DIR = SCRIPT_DIR.parent.parent / "frontend"
sys.path.insert(0, str(BACKEND_DIR))

# Configure test environment
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_parse_only.db")


def search_in_file(pattern, filepath):
    """Search for a regex pattern in a file."""
    try:
        content = filepath.read_text()
        return bool(re.search(pattern, content))
    except Exception:
        return False


def search_in_directory(pattern, directory):
    """Search for a regex pattern across all .py files in directory."""
    matches = []
    for filepath in directory.rglob("*.py"):
        if search_in_file(pattern, filepath):
            matches.append(str(filepath.relative_to(BACKEND_DIR)))
    return matches


def check_database_columns():
    """Check if database columns are actually used in queries."""
    print("=" * 60)
    print("DATABASE COLUMNS CHECK")
    print("=" * 60)
    
    queries = {
        "description": r"DBMeal\.description(?!\w)",
        "description_de": r"DBMeal\.description_de(?!\w)",
        "description_en": r"DBMeal\.description_en(?!\w)",
    }
    
    for col, pattern in queries.items():
        matches = search_in_directory(pattern, BACKEND_DIR)
        used = len(matches) > 0
        status = "✓ USED" if used else "✗ NOT USED"
        print(f"{col:20s} {status}")
        if used:
            print(f"                       Found in: {', '.join(matches[:3])}")
    
    return True


def check_rating_classes():
    """Check if RatingOut classes are actually used."""
    print("\n" + "=" * 60)
    print("RATING OUT CLASSES CHECK")
    print("=" * 60)
    
    # Check for class definitions
    main_content = (BACKEND_DIR / "main.py").read_text()
    
    # Find actual usages (not definitions)
    usage_pattern = r"\bRatingOut\b"
    usage_matches = re.findall(usage_pattern, main_content)
    print(f"RatingOut total mentions: {len(usage_matches)}")
    
    # Check if used in return types
    for line_num, line in enumerate(main_content.split('\n'), 1):
        if '@app.' in line and '->' in line:
            if 'RatingOut' in line or 'List[RatingOut' in line:
                print(f"  Used in endpoint definition at line {line_num}")
    
    # Check SideRatingOut
    side_pattern = r"\bSideRatingOut\b"
    side_matches = re.findall(side_pattern, main_content)
    print(f"SideRatingOut mentions: {len(side_matches)}")
    
    return True


def check_apis():
    """Check if all API endpoints are actually used."""
    print("\n" + "=" * 60)
    print("API ENDPOINTS CHECK")
    print("=" * 60)
    
    api_endpoints = [
        "/api/v1/mensas",
        "/api/v1/meals",
        "/api/v1/meals/search",
        "/api/v1/meals/{meal_id}/ratings",
        "/api/v1/ratings/{rating_id}",
        "/api/v1/meals/{meal_id}/side-ratings",
    ]
    
    for endpoint in api_endpoints:
        # Check if endpoint is defined
        if f'"{endpoint}"' in (BACKEND_DIR / "main.py").read_text() or f"'{endpoint}'" in (BACKEND_DIR / "main.py").read_text():
            print(f"{endpoint:45s} ✓ DEFINED")
    
    return True


def check_tests():
    """Check if test files actually run."""
    print("\n" + "=" * 60)
    print("TEST FILES CHECK")
    print("=" * 60)
    
    package_json = FRONTEND_DIR / "package.json"
    if package_json.exists():
        content = package_json.read_text()
        has_test = "test" in content or "jest" in content or " vitest" in content
        print(f"frontend/package.json has 'test' script: {'✓' if has_test else '✗'}")
    
    # Check if translation tests are referenced
    test_file = FRONTEND_DIR / "src" / "translations" / "translations.test.js"
    if test_file.exists():
        print(f"frontend/src/translations/translations.test.js: ✓ EXISTS")
        
        # Check if referenced in package.json
        package_content = package_json.read_text() if package_json.exists() else ""
        if "translations.test" in package_content:
            print("  → Referenced in package.json: ✓")
        else:
            print("  → Referenced in package.json: ✗ NOT REFERENCED")
    else:
        print("frontend/src/translations/translations.test.js: ✗ NOT FOUND")
    
    # Check translation files structure
    de_json = FRONTEND_DIR / "src" / "translations" / "de.json"
    en_json = FRONTEND_DIR / "src" / "translations" / "en.json"
    
    if de_json.exists() and en_json.exists():
        with open(de_json) as f:
            de = json.load(f)
        with open(en_json) as f:
            en = json.load(f)
        
        # Check structure matches
        def collect_keys(d, prefix=""):
            result = set()
            for k, v in d.items():
                full_key = f"{prefix}.{k}" if prefix else k
                if isinstance(v, dict):
                    result.update(collect_keys(v, full_key))
                else:
                    result.add(full_key)
            return result
        
        de_keys = collect_keys(de)
        en_keys = collect_keys(en)
        
        if de_keys == en_keys:
            print("translation files: ✓ identical structure")
        else:
            print(f"translation files: ✗ structure mismatch")
            print(f"  DE only: {de_keys - en_keys}")
            print(f"  EN only: {en_keys - de_keys}")
    
    return True


def check_apis_have_no_duplicate_classes():
    """Check if RatingOut class definitions have duplicates."""
    print("\n" + "=" * 60)
    print("DUPLICATE CLASS DEFINITIONS CHECK")
    print("=" * 60)
    
    main_content = (BACKEND_DIR / "main.py").read_text()
    
    # Count RatingOut base class definitions only (not subclasses)
    rating_out_def_count = len(re.findall(r'^class RatingOut\(BaseModel\)', main_content, re.MULTILINE))
    rating_out_with_meal_def_count = len(re.findall(r'^class RatingOut\(RatingOutWithMeal\)', main_content, re.MULTILINE))
    
    total_definitions = rating_out_def_count + rating_out_with_meal_def_count
    print(f"RatingOut total class definitions: {rating_out_def_count} base + {rating_out_with_meal_def_count} with Meal = {total_definitions}")
    if total_definitions > 1:
        print("  → Duplicate definition found!")
        return False
    else:
        print("  → No duplicates")
    
    return True


def check_apis_have_unused_relationships():
    """Check if Meal model relationships are used."""
    print("\n" + "=" * 60)
    print("MODEL RELATIONSHIPS CHECK")
    print("=" * 60)
    
    # Check back_populates usage
    relationships = {
        "ratings": r"ratings\s*=.*back_populates",
        "side_ratings": r"side_ratings\s*=.*back_populates",
    }
    
    for rel, pattern in relationships.items():
        if re.search(pattern, (BACKEND_DIR / "database.py").read_text()):
            # Check if actually queried
            matches = search_in_directory(rf"\.{rel}\.", BACKEND_DIR)
            if matches:
                print(f"{rel:20s} ✓ USED")
            else:
                # back_populates just for ORM relation, not necessarily queried
                print(f"{rel:20s} ✓ DEFINED (ORM only)")
    
    return True


def main():
    """Run all checks."""
    print("\n" + "=" * 60)
    print("UNUSED ITEMS VERIFICATION TESTS")
    print("=" * 60 + "\n")
    
    results = []
    
    results.append(("Database columns", check_database_columns()))
    results.append(("Rating classes", check_rating_classes()))
    results.append(("API endpoints", check_apis()))
    results.append(("Test files", check_tests()))
    results.append(("Duplicate class definitions", check_apis_have_no_duplicate_classes()))
    results.append(("Model relationships", check_apis_have_unused_relationships()))
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    for name, success in results:
        status = "✓" if success else "✗"
        print(f"{status} {name}")
    
    # Check for items that should be removed
    print("\n" + "=" * 60)
    print("RECOMMENDATIONS")
    print("=" * 60)
    
    # Check if description column is truly needed
    description_matches = search_in_directory(r"DBMeal\.description(?!\w)", BACKEND_DIR)
    if len(description_matches) == 1 and any("search_menu" in m for m in description_matches):
        print("✗ description column: MAYBE UNUSED (only used in search filter)")
    
    # Check for translation test integration
    package_json = FRONTEND_DIR / "package.json"
    if package_json.exists():
        content = package_json.read_text()
        if "translations.test" not in content:
            print("✗ translations.test.js: NOT INTEGRATED in CI/CD")
    
    return 0 if all(r[1] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())